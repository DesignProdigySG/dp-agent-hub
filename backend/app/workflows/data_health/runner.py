"""Starts or resumes a data health scan for a task.

One scan per agent at a time: a task finds the agent's unfinished scan (it stopped on an
error or a restart) and continues it from where it got to, unless the task asks for
`fresh: true`. A finished scan logs one workflow_log row whose data points the Results view
at the scan.
"""

import logging

from sqlmodel import select

from app.db import HealthScan, session
from app.events.schema import utcnow
from app.reporting import KpiDef
from app.workflows import BatchContext, ThreadOutcome, WorkflowSpec
from app.workflows.data_health import config as scan_config
from app.workflows.data_health.graph import build

log = logging.getLogger(__name__)
WORKFLOW = "data_health_scan"


def _thread(scan_id: str) -> str:
    return f"scan-{scan_id}"


def unfinished(agent_id: str) -> HealthScan | None:
    with session() as s:
        return s.exec(select(HealthScan).where(HealthScan.agent_id == agent_id,
                                               HealthScan.status != "done")
                      .order_by(HealthScan.started_at.desc())).first()


def _set(scan_id: str, **fields) -> None:
    with session() as s:
        scan = s.get(HealthScan, scan_id)
        for k, v in fields.items():
            setattr(scan, k, v)
        scan.updated_at = utcnow()
        s.add(scan)
        s.commit()


async def run_batch(ctx: BatchContext) -> tuple[str, int]:
    if not ctx.enabled:
        return "Agent disabled", 0
    cfg = scan_config.load(ctx.template_params, ctx.task_params)
    scan = unfinished(ctx.agent_id)
    if scan is not None and ctx.task_params.get("fresh"):
        _set(scan.id, status="failed", error="Replaced by a fresh scan")
        scan = None
    resumed = scan is not None
    if scan is None:
        scan = HealthScan(task_id=ctx.task_id, agent_id=ctx.agent_id,
                          params=cfg.model_dump(mode="json"))
        with session() as s:
            s.add(scan)
            s.commit()
    else:  # carry on with the settings it started with
        cfg = scan_config.ScanConfig.model_validate(scan.params)
        _set(scan.id, status="running", error="",
             counts={**scan.counts, "resumed": scan.counts.get("resumed", 0) + 1})
    thread_id = _thread(scan.id)
    started = bool(await ctx.state(thread_id))
    inputs = None if started else {
        "task_id": ctx.task_id, "agent_id": ctx.agent_id, "scan_id": scan.id,
        "cfg": cfg.model_dump(mode="json"), "model_tier": ctx.model_tier,
        "skills": list(ctx.skill_names)}
    try:
        await ctx.stream(thread_id, inputs)
    except Exception as e:
        error = f"{type(e).__name__}: {e}"[:500]
        _set(scan.id, status="failed", error=error)
        with session() as s:
            at = s.get(HealthScan, scan.id)
        raise RuntimeError(f"{error}. The scan stopped in its {at.phase} phase; run the task "
                           "again to continue from there.") from e
    with session() as s:
        scan = s.get(HealthScan, scan.id)
    ctx.report(*scan_report(scan.kpis))
    ctx.log(thread_id=thread_id, item_id=scan.id, status="DONE", action="data_health_scan",
            score=round(scan.kpis.get("dimensions", {}).get("overall", {}).get("avg", 0)),
            summary=f"{scan.kpis.get('total', 0)} leads scanned",
            data={"kind": "health_scan", "scan_id": scan.id, "resumed": resumed})
    when = scan.finished_at or utcnow()
    head = f"## Data health scan · {when:%d %b %Y}\n\n"
    if resumed:
        head += "_Continued an earlier scan from where it stopped._\n\n"
    tail = await _hand_off(ctx, scan, cfg) if cfg.handoff_to else ""
    return head + scan.report + tail, 0


async def _hand_off(ctx: BatchContext, scan: HealthScan, cfg: scan_config.ScanConfig) -> str:
    """The best leads the scan found (reachable, not duplicates), handed on to qualify."""
    from app.db import LeadHealth
    from app.handoff import HandoffError

    with session() as s:
        rows = s.exec(select(LeadHealth).where(
            LeadHealth.scan_id == scan.id, LeadHealth.dup_role != "duplicate",
            LeadHealth.reach.contains("email")).order_by(LeadHealth.overall.desc())
            .limit(cfg.handoff_max)).all()
    ids = [r.lead_id for r in rows]
    if not ids:
        return "\n\n_Nothing to hand on: no reachable leads in this scan._\n"
    brief = (f"The data health scan found {len(ids)} well-filled, reachable leads worth "
             f"qualifying (health scores {rows[0].overall}\u2013{rows[-1].overall} of 100). "
             "Please qualify and route them.")
    try:
        task = await ctx.hand_off(cfg.handoff_to, f"Qualify {len(ids)} leads from the data "
                                  "health scan", brief, ids)
    except HandoffError as e:
        return f"\n\n_Hand-off to {cfg.handoff_to!r} failed: {e}._\n"
    return (f"\n\n**Handed off** {len(ids)} leads to {task.params.get('to_agent_name')}: "
            f"task `{task.id}`.\n")


KPIS = (
    KpiDef("overall", "Health score", "score", "up", "Weighted average of the seven dimensions"),
    *(KpiDef(d, d.title(), "score", "up") for d in (
        "uniqueness", "completeness", "normalization", "accuracy", "contactability",
        "recency", "engagement")),
    KpiDef("leads_scanned", "Leads scanned", "count", None),
    KpiDef("usable_pct", "Usable by email or phone", "pct", "up"),
    KpiDef("unreachable_email", "Can't be emailed", "count", "down"),
    KpiDef("duplicates", "Duplicate records", "count", "down"),
    KpiDef("dormant", "No engagement", "count", "down"),
)


def scan_report(k: dict) -> tuple[str, dict[str, float]]:
    """A finished scan's headline and KPI values (the standard agent report)."""
    t = k.get("total", 0)
    dims = {d: v["avg"] for d, v in k.get("dimensions", {}).items()}
    c, dup = k.get("contactability", {}), k.get("duplicates", {})
    dormant = k.get("engagement_levels", {}).get("dormant", 0)
    values = {**dims, "leads_scanned": t, "unreachable_email": c.get("unreachable_email", 0),
              "duplicates": dup.get("redundant", 0), "dormant": dormant,
              "usable_pct": round(100 * c.get("usable", 0) / t, 1) if t else 0}
    headline = (f"Scanned {t:,} leads: health {dims.get('overall', 0):.0f}/100, "
                f"{c.get('unreachable_email', 0):,} can't be emailed, "
                f"{dup.get('groups', 0):,} duplicate group(s), {dormant:,} with no engagement.")
    return headline, values


def resume_value(choice: str, approver: str, note: str) -> dict[str, str]:
    return {"decision": choice, "approver": approver, "note": note}  # the scan never pauses


async def after_resume(ctx: BatchContext, thread_id: str, outcome: ThreadOutcome) -> str:
    return ""


SPEC = WorkflowSpec(
    id=WORKFLOW,
    name="Data health scan",
    description="Copies every lead and 18 months of engagement into the hub, scores each lead "
                "on the seven data health dimensions, and reports database-wide KPIs.",
    build=build,
    run_batch=run_batch,
    resume_value=resume_value,
    after_resume=after_resume,
    resumable=True,
    kpis=KPIS,
)
