"""Activity, KPI-trend and LLM-usage views for the Insights page."""

import asyncio
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request

from app import analytics
from app.security import require_admin, require_viewer

viewer = APIRouter(prefix="/insights", dependencies=[Depends(require_viewer)])
admin = APIRouter(prefix="/insights", dependencies=[Depends(require_admin)])


@viewer.get("/activities")
async def activities(days: int = Query(7, ge=1, le=365)) -> dict:
    return await asyncio.to_thread(analytics.activity_summary, days)


@viewer.get("/activities/recent")
async def recent(limit: int = Query(50, ge=1, le=500)) -> list[dict]:
    return await asyncio.to_thread(analytics.recent_activities, limit)


@viewer.get("/kpis")
async def kpis(days: int = Query(30, ge=1, le=730), scope: str | None = None) -> list[dict]:
    return await asyncio.to_thread(analytics.kpi_series, days, scope)


@admin.get("/llm")
async def llm_usage(days: int = Query(30, ge=1, le=365)) -> dict:
    return await asyncio.to_thread(analytics.llm_usage_summary, days)


@viewer.get("/ingestion")
def ingestion(request: Request) -> dict:
    return request.app.state.ingestor.status()


@admin.post("/snapshot")
async def snapshot_now(request: Request, day: str = "today") -> dict:
    """Snapshot today so far (or `yesterday`); the scheduled run replaces it later."""
    target = datetime.now(UTC).date() - (timedelta(days=1) if day == "yesterday" else
                                         timedelta())
    n = await request.app.state.snapshots.run(target, live=day != "yesterday")
    return {"date": target.isoformat(), "metrics": n}
