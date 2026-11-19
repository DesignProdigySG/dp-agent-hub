"""Daily KPI snapshots.

After `snapshot_hour_utc` each day, the previous UTC day is captured into kpi_snapshot:
agent KPIs (latest values as of end of day), task and approval throughput, activity volume
by type, LLM calls/tokens/cost, and governor usage. Rows are upserted, so a manual
"snapshot now" for today can be re-run and is replaced by the final one. Each snapshot is also
archived to the Data Lake, and old activities are purged per the retention setting.
"""

import asyncio
import logging
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import case, delete, func
from sqlmodel import select

from app.analytics import day_bounds
from app.config import get_settings
from app.db import (
    AgentRun,
    Approval,
    KpiSnapshot,
    LlmUsage,
    MarketoActivity,
    Task,
    session,
)
from app.events.schema import ApprovalStatus, TaskStatus

log = logging.getLogger(__name__)
HEALTH_SCOPE = "data_health"
NUMBER = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*%?\s*$")


def as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = NUMBER.match(str(value))
    return float(m.group(1)) if m else None


def collect(day: date, live_metrics: dict[str, dict[str, Any]] | None = None,
            governor_daily_used: int | None = None) -> list[dict[str, Any]]:
    start, end = day_bounds(day)
    rows: list[dict[str, Any]] = []

    def add(scope: str, scope_id: str, metric: str, value: Any) -> None:
        num = as_number(value)
        rows.append({"scope": scope, "scope_id": scope_id, "metric": metric, "value_num": num,
                     "value_text": None if num is not None and not isinstance(value, str)
                     else str(value)})

    with session() as s:
        # Agent KPIs: most recent finished run on or before the end of the day.
        latest = (select(AgentRun.agent_id, func.max(AgentRun.finished_at).label("at"))
                  .where(AgentRun.finished_at < end).group_by(AgentRun.agent_id).subquery())
        runs = s.exec(select(AgentRun).join(latest, (AgentRun.agent_id == latest.c.agent_id)
                                            & (AgentRun.finished_at == latest.c.at))).all()
        metrics = {r.agent_id: dict(r.metrics) for r in runs}
        for agent_id, live in (live_metrics or {}).items():
            metrics.setdefault(agent_id, {}).update(live)
        for agent_id, values in metrics.items():
            for k, v in values.items():
                add("agent", agent_id, k, v)

        runs_today = s.exec(
            select(AgentRun.agent_id, func.count(),
                   func.sum(case((AgentRun.status == TaskStatus.FAILED, 1), else_=0)))
            .where(AgentRun.finished_at >= start, AgentRun.finished_at < end)
            .group_by(AgentRun.agent_id)).all()
        for agent_id, n, failed in runs_today:
            add("agent", agent_id, "runs", int(n))
            add("agent", agent_id, "failed_runs", int(failed or 0))

        created = s.exec(select(func.count()).select_from(Task)
                         .where(Task.created_at >= start, Task.created_at < end)).one()
        add("tasks", "", "created", int(created))
        for status in (TaskStatus.DONE, TaskStatus.FAILED):
            n = s.exec(select(func.count()).select_from(AgentRun)
                       .where(AgentRun.status == status, AgentRun.finished_at >= start,
                              AgentRun.finished_at < end)).one()
            add("tasks", "", status.value, int(n))
        backlog = s.exec(select(func.count()).select_from(Task)
                         .where(Task.status.in_([TaskStatus.QUEUED,
                                                 TaskStatus.NEEDS_APPROVAL]))).one()
        add("tasks", "", "open_backlog", int(backlog))

        for status in (ApprovalStatus.APPROVED, ApprovalStatus.REJECTED):
            n = s.exec(select(func.count()).select_from(Approval)
                       .where(Approval.status == status, Approval.decided_at >= start,
                              Approval.decided_at < end)).one()
            add("approvals", "", status.value, int(n))

        acts = s.exec(select(MarketoActivity.activity_type, func.count())
                      .where(MarketoActivity.occurred_at >= start,
                             MarketoActivity.occurred_at < end)
                      .group_by(MarketoActivity.activity_type)).all()
        add("activities", "", "total", sum(int(n) for _, n in acts))
        for t, n in acts:
            add("activities", t, "count", int(n))
        engaged = s.exec(select(func.count(func.distinct(MarketoActivity.lead_id)))
                         .where(MarketoActivity.occurred_at >= start,
                                MarketoActivity.occurred_at < end)).one()
        add("activities", "", "engaged_leads", int(engaged or 0))

        llm = s.exec(select(func.count(), func.coalesce(func.sum(LlmUsage.cost_usd), 0.0),
                            func.coalesce(func.sum(LlmUsage.input_tokens), 0),
                            func.coalesce(func.sum(LlmUsage.output_tokens), 0),
                            func.sum(case((LlmUsage.ok.is_(False), 1), else_=0)))
                     .where(LlmUsage.ts >= start, LlmUsage.ts < end)).one()
        add("llm", "", "calls", int(llm[0] or 0))
        add("llm", "", "cost_usd", round(float(llm[1] or 0), 4))
        add("llm", "", "input_tokens", int(llm[2] or 0))
        add("llm", "", "output_tokens", int(llm[3] or 0))
        add("llm", "", "failures", int(llm[4] or 0))

    if governor_daily_used is not None:
        add("governor", "", "marketo_calls", governor_daily_used)
    return rows


def save(day: date, rows: list[dict[str, Any]]) -> int:
    """Replace the snapshot for `day` atomically. Data health KPIs are written by each scan
    (workflows/data_health) and are left alone."""
    with session() as s:
        s.exec(delete(KpiSnapshot).where(KpiSnapshot.snapshot_date == day,
                                         KpiSnapshot.scope != HEALTH_SCOPE))
        for r in rows:
            s.add(KpiSnapshot(snapshot_date=day, **r))
        s.commit()
    return len(rows)


def has_snapshot(day: date) -> bool:
    with session() as s:
        return s.exec(select(KpiSnapshot.id).where(KpiSnapshot.snapshot_date == day)
                      .limit(1)).first() is not None


class SnapshotScheduler:
    def __init__(self, hub) -> None:
        self.hub = hub
        self._task: asyncio.Task | None = None
        self.last_run: str = ""

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def run(self, day: date, *, live: bool = False) -> int:
        live_metrics = ({aid: st.metrics for aid, st in self.hub.statuses.items()}
                        if live else None)
        gov = self.hub.deps.governor.stats().daily_used if live else None
        rows = await asyncio.to_thread(collect, day, live_metrics, gov)
        n = await asyncio.to_thread(save, day, rows)
        await self.hub.deps.lake.write("kpi_snapshots", [
            {"snapshot_date": day.isoformat(), **r} for r in rows], day=day, name="snapshot")
        self.last_run = datetime.now(UTC).isoformat()
        log.info("KPI snapshot for %s: %d metrics", day, n)
        return n

    async def _loop(self) -> None:
        while True:
            try:
                s = get_settings()
                now = datetime.now(UTC)
                yesterday = now.date() - timedelta(days=1)
                if now.hour >= s.snapshot_hour_utc and not await asyncio.to_thread(
                        has_snapshot, yesterday):
                    await self.run(yesterday)
                    from app.ingest import purge_older_than

                    purged = await asyncio.to_thread(purge_older_than,
                                                     s.activity_retention_days)
                    if purged:
                        log.info("purged %d activities older than %d days", purged,
                                 s.activity_retention_days)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("snapshot scheduler tick failed")
            await asyncio.sleep(300)
