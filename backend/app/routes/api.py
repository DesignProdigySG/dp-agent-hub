"""Tasks, approvals, agents and audit. Reads need a viewer; every change needs the admin."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import select

from app import attachments, messages
from app.agents import registry
from app.config import get_settings
from app.db import Approval, AuditEntry, Task, TaskAttachment, WorkflowLog, audit, session
from app.events.schema import ApprovalOut, ApprovalStatus, TaskOut, TaskStatus, utcnow
from app.hub import Hub, add_feedback_round, workflow_for
from app.marketo import links
from app.security import require_admin, require_viewer

public = APIRouter()
viewer = APIRouter(dependencies=[Depends(require_viewer)])
admin = APIRouter(dependencies=[Depends(require_admin)])


def hub(request: Request) -> Hub:
    return request.app.state.hub


@public.get("/health")
def health() -> dict:
    return {"status": "ok"}


# --- tasks --------------------------------------------------------------------------------


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    agent_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    scheduled_for: datetime | None = None
    attachment_ids: list[str] = Field(default_factory=list, max_length=20)  # uploaded files


class TaskPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    params: dict[str, Any] | None = None
    scheduled_for: datetime | None = None
    attachment_ids: list[str] = Field(default_factory=list, max_length=20)  # files to add
    remove_attachment_ids: list[str] = Field(default_factory=list, max_length=50)


class Requeue(TaskPatch):
    """Run a finished task again (fresh run), optionally with edits, in one step."""


ACTIVE = (TaskStatus.IN_PROGRESS, TaskStatus.NEEDS_APPROVAL)
HISTORY_CHARS = 4000


def _editable(s, task_id: str) -> Task:
    task = s.get(Task, task_id)
    if task is None:
        raise HTTPException(404, "task not found")
    if task.status in ACTIVE:
        raise HTTPException(409, f"task is {task.status.value.replace('_', ' ')}; wait until "
                                 "it has finished")
    return task


def _apply(s, task: Task, body: TaskPatch, *, files_round: int = 0) -> None:
    """Field edits and attachment changes, in the caller's transaction."""
    for k, v in body.model_dump(exclude_unset=True,
                                exclude={"attachment_ids", "remove_attachment_ids"}).items():
        if v is None and k != "scheduled_for":  # only the time can be cleared (= ASAP)
            continue
        if k == "params":
            v = {**v, **({"revisions": task.params["revisions"]}
                         if "revisions" in (task.params or {}) else {})}
        setattr(task, k, v)
    try:
        attachments.link(s, body.attachment_ids, task_id=task.id, round=files_round)
    except attachments.AttachmentError as e:
        raise HTTPException(422, str(e)) from None
    for att_id in body.remove_attachment_ids:
        a = s.get(TaskAttachment, att_id)
        if a is None or a.task_id != task.id:
            raise HTTPException(422, f"attachment {att_id} isn't on this task")
        s.delete(a)
    task.updated_at = utcnow()
    s.add(task)


@viewer.get("/tasks", response_model=list[TaskOut])
def list_tasks() -> list[TaskOut]:
    with session() as s:
        return [t.out() for t in s.exec(select(Task).order_by(Task.created_at))]


@admin.post("/tasks", response_model=TaskOut, status_code=201)
async def create_task(body: TaskIn, request: Request) -> TaskOut:
    agent = registry.get(body.agent_id)
    if agent is None:
        raise HTTPException(422, f"unknown agent {body.agent_id!r}")
    if not agent.enabled:
        raise HTTPException(409, f"{agent.name} is disabled; enable it in Agents first")
    with session() as s:
        task = Task(**body.model_dump(exclude={"attachment_ids"}))
        s.add(task)
        try:  # the task and its files land together, so it never starts without them
            files = attachments.link(s, body.attachment_ids, task_id=task.id)
        except attachments.AttachmentError as e:
            raise HTTPException(422, str(e)) from None
        s.commit()
    audit("task_created", task.title + (f" ({len(files)} attachment(s))" if files else ""),
          task_id=task.id, agent_id=task.agent_id)
    await hub(request).task_changed(task)
    return task.out()


def _queued_task(s, task_id: str) -> Task:
    task = s.get(Task, task_id)
    if task is None:
        raise HTTPException(404, "task not found")
    if task.status != TaskStatus.QUEUED:
        raise HTTPException(409, f"task is {task.status}; only queued tasks can change")
    return task


@admin.patch("/tasks/{task_id}", response_model=TaskOut)
async def update_task(task_id: str, body: TaskPatch, request: Request) -> TaskOut:
    """Edit a queued task, or the record of a finished one (files only while queued)."""
    with session() as s:
        task = _editable(s, task_id)
        if task.status != TaskStatus.QUEUED and (body.attachment_ids
                                                 or body.remove_attachment_ids):
            raise HTTPException(409, "a finished task's files are what it used; move it back "
                                     "to queued to change them")
        _apply(s, task, body)
        s.commit()
    await hub(request).task_changed(task)
    return task.out()


@admin.post("/tasks/{task_id}/requeue", response_model=TaskOut)
async def requeue_task(task_id: str, body: Requeue, request: Request) -> TaskOut:
    """Move a finished task back to queued: the next run starts fresh (its own conversation),
    the previous result is kept in the task's history, and edits apply first."""
    with session() as s:
        task = _editable(s, task_id)
        if task.status == TaskStatus.QUEUED:
            raise HTTPException(409, "the task is already queued")
        params = dict(task.params or {})
        task.history = [*task.history, {
            "run": task.run, "status": task.status.value, "at": task.updated_at.isoformat(),
            "result": (task.result or "")[:HISTORY_CHARS],
            "feedback_rounds": len(params.pop("revisions", []) or [])}]
        task.params, task.run, task.result = params, task.run + 1, ""
        task.status, task.archived_at = TaskStatus.QUEUED, None
        if "scheduled_for" not in body.model_fields_set:
            task.scheduled_for = None  # ASAP unless a time is given
        # every file the task has (feedback rounds' too) is part of the fresh brief
        for a in s.exec(select(TaskAttachment).where(TaskAttachment.task_id == task.id)):
            a.round = 0
            s.add(a)
        _apply(s, task, body)
        s.commit()
    audit("task_requeued", f"{task.title} (run {task.run + 1})", task_id=task.id,
          agent_id=task.agent_id)
    await hub(request).task_changed(task)
    return task.out()


@admin.post("/tasks/{task_id}/archive", response_model=TaskOut)
async def archive_task(task_id: str, request: Request) -> TaskOut:
    """Hide a task from the board (a queued one won't run). Nothing is deleted."""
    with session() as s:
        task = _editable(s, task_id)
        task.archived_at = task.archived_at or utcnow()
        s.add(task)
        s.commit()
    audit("task_archived", task.title, task_id=task.id, agent_id=task.agent_id)
    await hub(request).task_changed(task)
    return task.out()


@admin.post("/tasks/{task_id}/unarchive", response_model=TaskOut)
async def unarchive_task(task_id: str, request: Request) -> TaskOut:
    with session() as s:
        task = s.get(Task, task_id)
        if task is None:
            raise HTTPException(404, "task not found")
        task.archived_at = None
        s.add(task)
        s.commit()
    audit("task_unarchived", task.title, task_id=task.id, agent_id=task.agent_id)
    await hub(request).task_changed(task)
    return task.out()


@admin.post("/tasks/{task_id}/run", response_model=TaskOut)
async def run_task_now(task_id: str, request: Request) -> TaskOut:
    with session() as s:
        task = _queued_task(s, task_id)
        task.scheduled_for, task.updated_at = None, utcnow()
        s.add(task)
        s.commit()
    await hub(request).task_changed(task)
    return task.out()


@viewer.get("/tasks/{task_id}/marketo")
def task_marketo_changes(task_id: str) -> dict[str, Any]:
    """What the task created or changed in Marketo, with links to open each in Marketo."""
    return {"changes": links.for_task(task_id),
            "links_configured": bool(get_settings().marketo_ui_url.strip())}


@admin.delete("/tasks/{task_id}", status_code=204)
async def delete_task(task_id: str, request: Request) -> None:
    with session() as s:
        task = s.get(Task, task_id)
        if task is None:
            raise HTTPException(404, "task not found")
        if task.status in (TaskStatus.IN_PROGRESS, TaskStatus.NEEDS_APPROVAL):
            raise HTTPException(409, "cannot delete a task that is running or awaiting approval")
        s.delete(task)
        s.commit()
    attachments.delete_for(task_id=task_id)
    await hub(request).task_deleted(task_id)


# --- approvals ----------------------------------------------------------------------------


class Decision(BaseModel):
    approved: bool
    comment: str = ""
    # Custom agents' tool reviews: replacement arguments for calls, by position.
    edits: dict[int, dict[str, Any]] | None = None
    # Workflow approvals: one of the approval's own choices (e.g. approve / downgrade / reject).
    choice: str | None = None
    # Approve only these: tool calls by position, or a workflow's picks by ID. The rest go
    # back to the agent with the comment.
    selected: list[int] | None = None


@viewer.get("/tasks/{task_id}/log")
def task_log(task_id: str) -> list[dict[str, Any]]:
    """What a workflow task decided, item by item (e.g. one row per lead)."""
    with session() as s:
        rows = s.exec(select(WorkflowLog).where(WorkflowLog.run_id == task_id)
                      .order_by(WorkflowLog.id)).all()
    # workflows listed in LEAD_WORKFLOWS log one row per lead: link each to Marketo
    return [{**r.model_dump(mode="json"), "marketo_url": links.url("lead", r.item_id)
             if r.workflow in LEAD_WORKFLOWS else None} for r in rows]


LEAD_WORKFLOWS: set[str] = set()  # ids of your workflows whose log items are lead IDs


@viewer.get("/approvals", response_model=list[ApprovalOut])
def list_approvals() -> list[ApprovalOut]:
    with session() as s:
        return [a.out() for a in s.exec(select(Approval).order_by(Approval.created_at))]


@admin.post("/approvals/{approval_id}/decision", response_model=ApprovalOut)
async def decide(approval_id: str, body: Decision, request: Request) -> ApprovalOut:
    try:
        approval = await hub(request).decide(approval_id, body.approved, body.comment,
                                             body.edits, choice=body.choice,
                                             selected=body.selected)
    except KeyError:
        raise HTTPException(404, "approval not found") from None
    except ValueError as e:
        raise HTTPException(409, str(e)) from None
    return approval.out()


@viewer.get("/tasks/{task_id}/messages")
def task_messages(task_id: str) -> list[dict[str, Any]]:
    """The conversation on a task: hand-offs, replies, approvals, notes, feedback."""
    return messages.for_task(task_id)


class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


@admin.post("/tasks/{task_id}/messages", status_code=201)
async def post_message(task_id: str, body: NoteIn, request: Request) -> dict[str, Any]:
    """Say something on a task. The agent hears it, like a reply in a chat:

    * waiting for you (an approval or a question): your message is your answer: the work
      goes back to the agent with it, and it revises and comes back to you;
    * finished: another round starts, in the same conversation;
    * not started yet: it's in the agent's brief. While it's working: a note on the task."""
    with session() as s:
        task = s.get(Task, task_id)
        if task is None:
            raise HTTPException(404, "task not found")
        waiting = s.exec(select(Approval).where(
            Approval.task_id == task_id, Approval.status == ApprovalStatus.PENDING)
            .order_by(Approval.created_at.desc())).first()
    d = registry.get(task.agent_id)
    agent_task = d is not None and not workflow_for(task, d)
    if waiting is not None and agent_task:
        reply = (waiting.details or {}).get("kind") == "reply"
        await hub(request).decide(waiting.id, reply, body.text,
                                  choice="reply" if reply else "revise")
        return messages.for_task(task_id)[-1]
    if agent_task and task.status in (TaskStatus.DONE, TaskStatus.FAILED):
        with session() as s:
            t = s.get(Task, task_id)
            add_feedback_round(t, body.text)
            s.add(t)
            s.commit()
        audit("task_feedback", body.text[:300], task_id=task_id, agent_id=task.agent_id)
        m = messages.add(task_id, messages.YOU, "You", "feedback", body.text)
        await hub(request).task_changed(t)
        return messages.out(m)
    m = messages.add(task_id, messages.YOU, "You", "note", body.text)
    await hub(request).task_changed(task)
    return messages.out(m)


@admin.get("/audit")
def audit_log(limit: int = 200) -> list[dict]:
    with session() as s:
        rows = s.exec(select(AuditEntry).order_by(AuditEntry.id.desc()).limit(min(limit, 1000)))
        return [r.model_dump(mode="json") for r in rows]
