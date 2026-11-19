"""Read-side queries over stored activities, KPI snapshots and LLM usage.

Agents use these instead of calling Marketo, so analysis costs no API quota.
"""

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import case, func
from sqlmodel import select

from app.db import KpiSnapshot, LlmUsage, MarketoActivity, session

# Relative intent weight of an activity, by Marketo activity type id.
ENGAGEMENT_WEIGHTS = {2: 10, 11: 5, 1: 2, 10: 1, 7: 0, 9: -5, 13: 1, 12: 0, 22: 1, 6: 0}


def _since(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


def activity_summary(days: int = 7) -> dict[str, Any]:
    since = _since(days)
    with session() as s:
        base = select(MarketoActivity).where(MarketoActivity.occurred_at >= since)
        total = s.exec(select(func.count()).select_from(base.subquery())).one()
        by_type = s.exec(
            select(MarketoActivity.activity_type, func.count())
            .where(MarketoActivity.occurred_at >= since)
            .group_by(MarketoActivity.activity_type).order_by(func.count().desc())
        ).all()
        top_assets = s.exec(
            select(MarketoActivity.primary_attribute_value, func.count())
            .where(MarketoActivity.occurred_at >= since,
                   MarketoActivity.primary_attribute_value.is_not(None))
            .group_by(MarketoActivity.primary_attribute_value)
            .order_by(func.count().desc()).limit(10)
        ).all()
        engaged = s.exec(
            select(func.count(func.distinct(MarketoActivity.lead_id)))
            .where(MarketoActivity.occurred_at >= since)
        ).one()
        day_col = func.date(MarketoActivity.occurred_at)
        per_day = s.exec(
            select(day_col, func.count()).where(MarketoActivity.occurred_at >= since)
            .group_by(day_col).order_by(day_col)
        ).all()
    return {
        "days": days,
        "total": int(total or 0),
        "engaged_leads": int(engaged or 0),
        "by_type": [{"type": t, "count": int(n)} for t, n in by_type],
        "top_assets": [{"asset": a, "count": int(n)} for a, n in top_assets],
        "per_day": [{"date": str(d), "count": int(n)} for d, n in per_day],
    }


def lead_engagement(lead_ids: list[int], days: int = 30) -> dict[int, int]:
    """Weighted engagement score per lead over the window (only leads with activity)."""
    if not lead_ids:
        return {}
    scores: dict[int, int] = defaultdict(int)
    since = _since(days)
    with session() as s:
        for i in range(0, len(lead_ids), 1000):  # stay under bind-parameter limits
            rows = s.exec(
                select(MarketoActivity.lead_id, MarketoActivity.activity_type_id, func.count())
                .where(MarketoActivity.occurred_at >= since,
                       MarketoActivity.lead_id.in_(lead_ids[i:i + 1000]))
                .group_by(MarketoActivity.lead_id, MarketoActivity.activity_type_id)
            ).all()
            for lead_id, type_id, n in rows:
                scores[int(lead_id)] += ENGAGEMENT_WEIGHTS.get(type_id or -1, 1) * int(n)
    return dict(scores)


def recent_activities(limit: int = 50) -> list[dict[str, Any]]:
    with session() as s:
        rows = s.exec(select(MarketoActivity).order_by(MarketoActivity.occurred_at.desc())
                      .limit(min(limit, 500))).all()
    return [{"id": r.id, "source": r.source, "lead_id": r.lead_id, "type": r.activity_type,
             "type_id": r.activity_type_id, "occurred_at": r.occurred_at.isoformat(),
             "asset": r.primary_attribute_value} for r in rows]


def kpi_series(days: int = 30, scope: str | None = None) -> list[dict[str, Any]]:
    start = datetime.now(UTC).date() - timedelta(days=days)
    with session() as s:
        q = select(KpiSnapshot).where(KpiSnapshot.snapshot_date >= start)
        if scope:
            q = q.where(KpiSnapshot.scope == scope)
        rows = s.exec(q.order_by(KpiSnapshot.snapshot_date)).all()
    return [{"date": r.snapshot_date.isoformat(), "scope": r.scope, "scope_id": r.scope_id,
             "metric": r.metric, "value": r.value_num, "text": r.value_text} for r in rows]


def llm_usage_summary(days: int = 30) -> dict[str, Any]:
    since = _since(days)
    with session() as s:
        by_model = s.exec(
            select(LlmUsage.model, LlmUsage.tier, func.count(),
                   func.sum(LlmUsage.input_tokens), func.sum(LlmUsage.output_tokens),
                   func.coalesce(func.sum(LlmUsage.cost_usd), 0.0),
                   func.sum(case((LlmUsage.ok.is_(False), 1), else_=0)))
            .where(LlmUsage.ts >= since)
            .group_by(LlmUsage.model, LlmUsage.tier)
        ).all()
        day_col = func.date(LlmUsage.ts)
        per_day = s.exec(
            select(day_col, func.coalesce(func.sum(LlmUsage.cost_usd), 0.0), func.count())
            .where(LlmUsage.ts >= since).group_by(day_col).order_by(day_col)
        ).all()
    models = [{"model": m, "tier": t, "calls": int(c), "input_tokens": int(i or 0),
               "output_tokens": int(o or 0), "cost_usd": round(float(cost or 0), 4),
               "failures": int(f or 0)} for m, t, c, i, o, cost, f in by_model]
    return {
        "days": days,
        "total_cost_usd": round(sum(m["cost_usd"] for m in models), 4),
        "calls": sum(m["calls"] for m in models),
        "by_model": sorted(models, key=lambda m: -m["cost_usd"]),
        "per_day": [{"date": str(d), "cost_usd": round(float(c or 0), 4), "calls": int(n)}
                    for d, c, n in per_day],
    }


def day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    return start, start + timedelta(days=1)
