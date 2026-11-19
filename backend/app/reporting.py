"""The standard way agents report on their work.

After a run, an agent records one **report**: a one-line headline ("Scanned 738 leads: ...")
and its KPI values. Which KPIs an agent has, their labels, units and which direction is good,
come from `KpiDef`s declared by the workflows it runs (`WorkflowSpec.kpis`). Every agent also
gets the same activity KPIs, computed from the task history.

`agent_report()` is what the profile panel shows: the latest headline, each KPI with its change
since the report from a week earlier (or since the previous report while there's no week of
history yet), a short trend, plain-language highlights, and the last 7 days of activity.

    python -m app.reporting backfill   # reports from data health scans that predate this
"""

import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import func
from sqlmodel import select

from app.db import AgentReport, Approval, DesignDeliverable, HealthScan, LlmUsage, Task, session
from app.events.schema import TaskStatus, utcnow
from app.marketo import links

Unit = Literal["score", "pct", "count", "usd"]
WEEK = timedelta(days=7)


@dataclass(frozen=True)
class KpiDef:
    key: str
    label: str
    unit: Unit = "count"
    better: Literal["up", "down"] | None = "up"  # None: neither direction is good or bad
    help: str = ""


def _aware(dt: datetime | None) -> datetime | None:
    from datetime import UTC

    return dt.replace(tzinfo=UTC) if dt and dt.tzinfo is None else dt


def record(agent_id: str, task_id: str | None, headline: str,
           kpis: dict[str, float | int | None], at: datetime | None = None) -> AgentReport:
    row = AgentReport(agent_id=agent_id, task_id=task_id, headline=headline.strip()[:500],
                      kpis={k: float(v) for k, v in kpis.items() if v is not None},
                      at=at or utcnow())
    with session() as s:
        s.add(row)
        s.commit()
    return row


def first_line(text: str, limit: int = 500) -> str:
    """A headline from free text: its first sentence-like line, without Markdown. A long line
    ends at its last full sentence that fits, never mid-word."""
    for line in text.splitlines():
        line = line.strip().lstrip("#*->|` ").replace("**", "").strip()
        if len(line) <= 3:
            continue
        if len(line) <= limit:
            return line
        cut = line[:limit]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        return cut[:end + 1] if end > limit // 4 else cut.rsplit(" ", 1)[0] + "…"
    return ""


# --- what each agent reports --------------------------------------------------------------------


def kpi_defs(d) -> list[KpiDef]:
    """The KPIs of the workflows an agent runs (its own, or ones its templates name)."""
    from app.workflows import registry

    specs = registry()
    wanted = [d.workflow] + [(t.get("params") or {}).get("workflow") for t in d.templates]
    out: list[KpiDef] = []
    for wf in dict.fromkeys(w for w in wanted if w):
        if wf in specs:
            out += [k for k in specs[wf].kpis if k.key not in {o.key for o in out}]
    if "save_design" in (d.tools or []):
        out += DESIGN_KPIS
    return out


DESIGN_KPIS = [
    KpiDef("design_pieces", "Pieces delivered", "count", None,
           "Landing pages, forms and emails saved in the last 7 days"),
    KpiDef("brand_pass_pct", "Brand check pass rate", "pct", "up",
           "Share of saved versions with no brand-check errors (last 7 days)"),
    KpiDef("feedback_rounds", "Feedback rounds", "count", "down",
           "Rounds of changes requested in the last 7 days"),
]


def _design_kpis(agent_id: str, since: datetime, until: datetime) -> dict[str, float]:
    with session() as s:
        rows = list(s.exec(select(DesignDeliverable).where(
            DesignDeliverable.agent_id == agent_id, DesignDeliverable.created_at >= since,
            DesignDeliverable.created_at < until)))
    if not rows:
        return {}
    latest = {(r.task_id, r.kind, r.name) for r in rows}
    passed = sum(not r.checks.get("errors") for r in rows)
    rounds = {(r.task_id, r.round) for r in rows if r.round}
    return {"design_pieces": len(latest), "brand_pass_pct": round(100 * passed / len(rows), 1),
            "feedback_rounds": len(rounds)}


def _activity(agent_id: str, since: datetime, until: datetime) -> dict[str, Any]:
    with session() as s:
        statuses = dict(s.exec(select(Task.status, func.count()).where(
            Task.agent_id == agent_id, Task.updated_at >= since, Task.updated_at < until,
            Task.status.in_([TaskStatus.DONE, TaskStatus.FAILED])).group_by(Task.status)).all())
        approvals = s.exec(select(func.count()).select_from(Approval).where(
            Approval.agent_id == agent_id, Approval.created_at >= since,
            Approval.created_at < until)).one()
        cost = s.exec(select(func.coalesce(func.sum(LlmUsage.cost_usd), 0.0)).where(
            LlmUsage.agent_id == agent_id, LlmUsage.ts >= since, LlmUsage.ts < until)).one()
        last = s.exec(select(func.max(Task.updated_at)).where(
            Task.agent_id == agent_id, Task.status == TaskStatus.DONE)).one()
    return {"tasks_done": int(statuses.get(TaskStatus.DONE, 0)),
            "tasks_failed": int(statuses.get(TaskStatus.FAILED, 0)),
            "approvals": int(approvals or 0), "cost_usd": round(float(cost or 0), 2),
            "last_done_at": _aware(last)}


# --- the profile panel's report -----------------------------------------------------------------


def _fmt(v: float, unit: Unit) -> str:
    if unit == "pct":
        return f"{v:.0f}%" if abs(v) >= 10 else f"{v:.1f}%"
    if unit == "usd":
        return f"${v:,.2f}"
    return f"{v:,.0f}" if float(v).is_integer() or abs(v) >= 100 else f"{v:,.1f}"


def _change(k: KpiDef, delta: float) -> str:
    amount = abs(delta)
    if k.unit in ("score", "pct"):
        text = f"{amount:.0f}" if k.unit == "score" and amount >= 1 else f"{amount:.1f}"
        return f"{text} pt" if text == "1" else f"{text} pts"
    return _fmt(amount, k.unit)


def agent_report(d, now: datetime | None = None) -> dict[str, Any]:
    now = now or utcnow()
    defs = kpi_defs(d)
    with session() as s:
        reports = list(s.exec(select(AgentReport).where(AgentReport.agent_id == d.id)
                              .order_by(AgentReport.at)))
    for r in reports:
        r.at = _aware(r.at)
    latest = reports[-1] if reports else None
    # the comparison: the last report at least a week old, else the one before the latest
    earlier = reports[:-1]
    baseline = next((r for r in reversed(earlier) if r.at <= now - WEEK), None)
    if baseline is None and earlier:
        baseline = earlier[-1]
    weekly = baseline is not None and baseline.at <= now - WEEK
    if baseline is None:
        compare = None
    elif weekly and baseline.at > now - 2 * WEEK:
        compare = "since last week"
    elif weekly:
        compare = f"since {baseline.at:%-d %b}"
    else:
        compare = f"since the previous run on {baseline.at:%-d %b}"

    values = dict(latest.kpis) if latest else {}
    base = dict(baseline.kpis) if baseline else {}
    if any(k is DESIGN_KPIS[0] for k in defs):  # computed from saved designs, not reported
        values |= _design_kpis(d.id, now - WEEK, now)
        week_before = _design_kpis(d.id, now - 2 * WEEK, now - WEEK)
        base = {**base, **week_before}
        if week_before and not compare:
            compare = "since last week"
    kpis, moves = [], []
    for k in defs:
        if k.key not in values:
            continue
        v, prev = values[k.key], base.get(k.key)
        delta = None if prev is None else round(v - prev, 2)
        trend = None if delta is None else "flat" if abs(delta) < 1e-9 else \
            ("up" if delta > 0 else "down")
        good = None if trend in (None, "flat") or k.better is None else \
            (trend == k.better)
        series = [{"at": r.at.isoformat(), "value": r.kpis[k.key]}
                  for r in reports[-12:] if k.key in r.kpis]
        kpis.append({"key": k.key, "label": k.label, "unit": k.unit, "better": k.better,
                     "help": k.help, "value": v, "display": _fmt(v, k.unit),
                     "previous": prev, "delta": delta, "trend": trend, "good": good,
                     "change": _change(k, delta) if delta else "", "series": series})
        if delta:
            scale = 100.0 if k.unit in ("score", "pct") else max(abs(prev or 0), 1.0)
            moves.append((abs(delta) / scale, k, v, prev, trend, good))
    moves.sort(key=lambda m: -m[0])
    highlights = []
    for _, k, v, prev, trend, good in moves[:3]:
        verb = "up" if trend == "up" else "down"
        highlights.append({"text": f"{k.label} {verb} {_change(k, v - prev)} {compare}: "
                                   f"{_fmt(prev, k.unit)} → {_fmt(v, k.unit)}",
                           "good": good})
    if latest and not baseline:
        highlights.append({"text": "First report: changes show from the next run.",
                           "good": None})
    elif baseline and not moves and kpis:
        highlights.append({"text": f"No change in any KPI {compare}.", "good": None})
    this_week = _activity(d.id, now - WEEK, now)
    last_week = _activity(d.id, now - 2 * WEEK, now - WEEK)
    return {
        "agent_id": d.id,
        "headline": {"text": latest.headline, "at": latest.at.isoformat(),
                     "task_id": latest.task_id} if latest else None,
        "compare": compare, "kpis": kpis, "highlights": highlights,
        "activity": {"days": 7, **this_week,
                     "last_done_at": this_week["last_done_at"].isoformat()
                     if this_week["last_done_at"] else None,
                     "previous": {k: v for k, v in last_week.items() if k != "last_done_at"}},
        "reports": len(reports),
        "marketo": links.for_agent(d.id, now - WEEK),
    }


# --- backfill ---------------------------------------------------------------------------------


def backfill() -> int:
    """Reports for finished data health scans recorded before agents reported."""
    from app.workflows.data_health.runner import scan_report

    n = 0
    with session() as s:
        scans = list(s.exec(select(HealthScan).where(HealthScan.status == "done")
                            .order_by(HealthScan.finished_at)))
        have = {r.task_id for r in s.exec(select(AgentReport))}
    for scan in scans:
        if scan.task_id in have:
            continue
        headline, values = scan_report(scan.kpis)
        record(scan.agent_id, scan.task_id, headline, values, at=_aware(scan.finished_at))
        n += 1
    return n


if __name__ == "__main__":
    if sys.argv[1:] != ["backfill"]:
        print("usage: python -m app.reporting backfill")
        sys.exit(2)
    from app.db import init_db

    init_db()
    print(f"recorded {backfill()} report(s)")
