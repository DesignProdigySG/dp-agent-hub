"""Recurring tasks. Viewers can see schedules; the admin creates, edits and runs them."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import select

from app import attachments, schedules
from app.agents import registry
from app.db import Schedule, Task, audit, session
from app.events.schema import TaskUpdatedMsg, utcnow
from app.security import require_admin, require_viewer

viewer = APIRouter(dependencies=[Depends(require_viewer)])
admin = APIRouter(dependencies=[Depends(require_admin)])


def _get(db, schedule_id: str) -> Schedule:
    s = db.get(Schedule, schedule_id)
    if s is None:
        raise HTTPException(404, "schedule not found")
    return s


def _link(db, ids: list[str], schedule_id: str) -> None:
    try:
        attachments.link(db, ids, schedule_id=schedule_id)
    except attachments.AttachmentError as e:
        raise HTTPException(422, str(e)) from None


def _check_agent(agent_id: str) -> None:
    if registry.get(agent_id) is None:
        raise HTTPException(422, f"unknown agent {agent_id!r}")


@viewer.get("/schedules")
def list_schedules() -> list[dict[str, Any]]:
    with session() as db:
        rows = db.exec(select(Schedule).order_by(Schedule.created_at)).all()
    return [schedules.out(s) for s in rows]


@admin.post("/schedules", status_code=201)
def create_schedule(body: schedules.ScheduleIn) -> dict[str, Any]:
    _check_agent(body.agent_id)
    s = Schedule(**body.model_dump(exclude={"attachment_ids"}))
    s.next_run_at = schedules.next_run(s, utcnow())
    with session() as db:
        db.add(s)
        _link(db, body.attachment_ids, s.id)
        db.commit()
    audit("schedule_created", f"{s.title}: {schedules.describe(s)}", agent_id=s.agent_id,
          data={"schedule_id": s.id})
    return schedules.out(s)


@admin.put("/schedules/{schedule_id}")
def update_schedule(schedule_id: str, body: schedules.ScheduleIn) -> dict[str, Any]:
    _check_agent(body.agent_id)
    with session() as db:
        s = _get(db, schedule_id)
        for k, v in body.model_dump(exclude={"attachment_ids"}).items():
            setattr(s, k, v)
        s.next_run_at = schedules.next_run(s, utcnow())
        s.updated_at = utcnow()
        db.add(s)
        _link(db, body.attachment_ids, s.id)
        db.commit()
    audit("schedule_updated", f"{s.title}: {schedules.describe(s)}"
          + ("" if s.enabled else " (paused)"), agent_id=s.agent_id, data={"schedule_id": s.id})
    return schedules.out(s)


@admin.delete("/schedules/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: str) -> None:
    with session() as db:
        s = _get(db, schedule_id)
        db.delete(s)
        db.commit()
    attachments.delete_for(schedule_id=schedule_id)
    audit("schedule_deleted", s.title, agent_id=s.agent_id, data={"schedule_id": s.id})


@admin.post("/schedules/{schedule_id}/run")
async def run_now(schedule_id: str, request: Request) -> dict[str, Any]:
    """Queue one run now; the regular cadence is unchanged."""
    with session() as db:
        s = _get(db, schedule_id)
        prev = db.get(Task, s.last_task_id) if s.last_task_id else None
        if prev is not None and prev.status in schedules.BLOCKING:
            raise HTTPException(409, "the previous run is still queued or running")
        task = Task(title=s.title, description=s.description, agent_id=s.agent_id,
                    params=dict(s.params), schedule_id=s.id)
        db.add(task)
        attachments.copy_to_task(s.id, task.id, db)
        s.last_run_at, s.last_task_id, s.last_note = utcnow(), task.id, ""
        db.add(s)
        db.commit()
    audit("task_created", f"{s.title} (run now from its schedule)", task_id=task.id,
          agent_id=s.agent_id, data={"schedule_id": s.id})
    await request.app.state.hub.deps.bus.broadcast(TaskUpdatedMsg(task=task.out()))
    return schedules.out(s)
