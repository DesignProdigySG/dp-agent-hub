"""Data health scans (workflows/data_health): progress, KPIs, and per-lead drill-down."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlmodel import select

from app.db import HealthScan, LeadHealth, LeadMirror, session
from app.marketo import links
from app.security import require_viewer
from app.workflows.data_health.config import DIMENSIONS

viewer = APIRouter(dependencies=[Depends(require_viewer)])

Dimension = Literal["overall", "uniqueness", "completeness", "normalization", "accuracy",
                    "contactability", "recency", "engagement"]
LEAD_FIELDS = ("firstName", "lastName", "email", "company", "title", "country", "leadSource")


def _summary(scan: HealthScan) -> dict[str, Any]:
    return {"id": scan.id, "task_id": scan.task_id, "agent_id": scan.agent_id,
            "status": scan.status, "phase": scan.phase, "counts": scan.counts,
            "error": scan.error, "started_at": scan.started_at,
            "finished_at": scan.finished_at,
            "overall": (scan.kpis.get("dimensions", {}).get("overall") or {}).get("avg"),
            "total": scan.kpis.get("total")}


def _get(scan_id: str) -> HealthScan:
    with session() as s:
        scan = s.get(HealthScan, scan_id)
    if scan is None:
        raise HTTPException(404, "scan not found")
    return scan


@viewer.get("/data-health/scans")
def list_scans(limit: int = Query(20, ge=1, le=100)) -> list[dict[str, Any]]:
    with session() as s:
        rows = s.exec(select(HealthScan).order_by(HealthScan.started_at.desc()).limit(limit))
        return [_summary(r) for r in rows]


@viewer.get("/data-health/scans/{scan_id}")
def get_scan(scan_id: str) -> dict[str, Any]:
    scan = _get(scan_id)
    return {**_summary(scan), "params": scan.params, "kpis": scan.kpis, "report": scan.report}


def _leads(ids: list[int]) -> dict[int, dict[str, Any]]:
    with session() as s:
        return {m.lead_id: {k: m.data.get(k) for k in LEAD_FIELDS}
                for m in s.exec(select(LeadMirror).where(LeadMirror.lead_id.in_(ids or [0])))}


@viewer.get("/data-health/scans/{scan_id}/leads")
def scan_leads(scan_id: str, sort: Dimension = "overall", issue: str | None = None,
               limit: int = Query(50, ge=1, le=500),
               offset: int = Query(0, ge=0)) -> dict[str, Any]:
    """Leads worst-first on one dimension, optionally only those with an issue code."""
    _get(scan_id)
    col = getattr(LeadHealth, sort)
    with session() as s:
        q = select(LeadHealth).where(LeadHealth.scan_id == scan_id)
        if issue:  # issues is JSON; filter in Python, it's at most one scan's rows
            rows = [r for r in s.exec(q.order_by(col, LeadHealth.lead_id))
                    if any(i.get("code") == issue for i in r.issues)]
            total, rows = len(rows), rows[offset:offset + limit]
        else:
            total = s.exec(select(func.count()).select_from(LeadHealth)
                           .where(LeadHealth.scan_id == scan_id)).one()
            rows = list(s.exec(q.order_by(col, LeadHealth.lead_id).offset(offset).limit(limit)))
    leads = _leads([r.lead_id for r in rows])
    return {"total": total, "rows": [
        {"lead_id": r.lead_id, "lead": leads.get(r.lead_id, {}),
         "marketo_url": links.url("lead", r.lead_id),
         "scores": {d: getattr(r, d) for d in (*DIMENSIONS, "overall")},
         "engagement_level": r.engagement_level, "reach": r.reach, "dup_group": r.dup_group,
         "dup_role": r.dup_role, "issues": r.issues} for r in rows]}


@viewer.get("/data-health/scans/{scan_id}/duplicates")
def scan_duplicates(scan_id: str, limit: int = Query(50, ge=1, le=500),
                    offset: int = Query(0, ge=0)) -> dict[str, Any]:
    _get(scan_id)
    with session() as s:
        rows = list(s.exec(select(LeadHealth).where(LeadHealth.scan_id == scan_id,
                                                    LeadHealth.dup_group != "")
                           .order_by(LeadHealth.dup_group, LeadHealth.lead_id)))
    groups: dict[str, list[LeadHealth]] = {}
    for r in rows:
        groups.setdefault(r.dup_group, []).append(r)
    page = list(groups.items())[offset:offset + limit]
    leads = _leads([r.lead_id for _, members in page for r in members])
    return {"total": len(groups), "groups": [
        {"group": gid, "members": [
            {"lead_id": r.lead_id, "role": r.dup_role, "lead": leads.get(r.lead_id, {}),
             "marketo_url": links.url("lead", r.lead_id),
             "completeness": r.completeness,
             "matched_on": next((i["message"].split("matched on ")[-1].rstrip(")")
                                 for i in r.issues if i["code"] in ("duplicate",
                                                                    "has_duplicates")), "")}
            for r in sorted(members, key=lambda m: m.dup_role != "survivor")]}
        for gid, members in page]}
