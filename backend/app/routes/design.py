"""Designer deliverables: versions, previews, Marketo-ready exports, and feedback rounds."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import select

from app import attachments, design, messages
from app.agents import registry
from app.db import DesignDeliverable, Task, audit, session
from app.events.schema import TaskStatus
from app.hub import add_feedback_round, workflow_for
from app.security import require_admin, require_viewer

viewer = APIRouter(dependencies=[Depends(require_viewer)])
admin = APIRouter(dependencies=[Depends(require_admin)])


def _summary(d: DesignDeliverable) -> dict[str, Any]:
    return {"id": d.id, "kind": d.kind, "name": d.name, "version": d.version, "round": d.round,
            "subject": d.subject, "preheader": d.preheader, "spec": d.spec,
            "marketo": d.marketo, "checks": d.checks, "created_at": d.created_at}


@viewer.get("/tasks/{task_id}/designs")
def task_designs(task_id: str) -> list[dict[str, Any]]:
    """Each deliverable (kind + name) with all its versions, newest first."""
    with session() as s:
        rows = list(s.exec(select(DesignDeliverable)
                           .where(DesignDeliverable.task_id == task_id)
                           .order_by(DesignDeliverable.created_at)))
    groups: dict[tuple[str, str], list[DesignDeliverable]] = {}
    for r in rows:
        groups.setdefault((r.kind, r.name), []).append(r)
    order = {"landing_page": 0, "form": 1, "email": 2}
    return [{"kind": k, "name": n, "versions": [_summary(v) for v in reversed(vs)]}
            for (k, n), vs in sorted(groups.items(), key=lambda g: order.get(g[0][0], 9))]


@viewer.get("/designs/{design_id}")
def get_design(design_id: str, mode: Literal["preview", "export"] = "preview") -> dict:
    with session() as s:
        d = s.get(DesignDeliverable, design_id)
    if d is None:
        raise HTTPException(404, "design not found")
    return {**_summary(d), "html": design.render(d, mode)}


class FeedbackIn(BaseModel):
    feedback: str = Field(min_length=3, max_length=5000)
    attachment_ids: list[str] = Field(default_factory=list, max_length=20)


@admin.post("/tasks/{task_id}/feedback")
async def give_feedback(task_id: str, body: FeedbackIn, request: Request) -> dict:
    """Start another round: the agent continues the same task with this feedback."""
    with session() as s:
        task = s.get(Task, task_id)
        if task is None:
            raise HTTPException(404, "task not found")
        d = registry.get(task.agent_id)
        if d is None or workflow_for(task, d):
            raise HTTPException(409, "feedback rounds are for agent tasks, not workflows")
        if task.status not in (TaskStatus.DONE, TaskStatus.FAILED):
            raise HTTPException(409, "wait until the task has finished")
        n = add_feedback_round(task, body.feedback)
        s.add(task)
        try:
            attachments.link(s, body.attachment_ids, task_id=task_id, round=n)
        except attachments.AttachmentError as e:
            raise HTTPException(422, str(e)) from None
        s.commit()
    audit("task_feedback", body.feedback[:300], task_id=task_id, agent_id=task.agent_id)
    messages.add(task_id, messages.YOU, "You", "feedback", body.feedback)
    await request.app.state.hub.task_changed(task)
    return {"round": n, "status": task.status.value}
