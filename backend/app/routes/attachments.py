"""Task attachments: upload, list, read, remove, and keep one as agent knowledge."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlmodel import select

from app import attachments, knowledge
from app.db import KnowledgeDoc, Task, TaskAttachment, audit, session
from app.events.schema import TaskStatus
from app.security import require_admin, require_viewer

viewer = APIRouter(dependencies=[Depends(require_viewer)])
admin = APIRouter(dependencies=[Depends(require_admin)])


@admin.post("/attachments", status_code=201)
async def upload(file: UploadFile) -> dict[str, Any]:
    """Upload a file; then pass its id in a task's (or schedule's, or feedback's)
    attachment_ids."""
    data = await file.read(attachments.MAX_BYTES + 1)
    try:
        a = attachments.store(file.filename or "attachment.txt", data)
    except attachments.AttachmentError as e:
        raise HTTPException(415 if "use Markdown" in str(e) else 422, str(e)) from None
    return attachments.summary(a)


@viewer.get("/tasks/{task_id}/attachments")
def task_attachments(task_id: str) -> list[dict[str, Any]]:
    return [attachments.summary(a) for a in attachments.for_task(task_id)]


@viewer.get("/schedules/{schedule_id}/attachments")
def schedule_attachments(schedule_id: str) -> list[dict[str, Any]]:
    with session() as s:
        rows = s.exec(select(TaskAttachment).where(TaskAttachment.schedule_id == schedule_id)
                      .order_by(TaskAttachment.created_at))
        return [attachments.summary(a) for a in rows]


def _get(s, attachment_id: str) -> TaskAttachment:
    a = s.get(TaskAttachment, attachment_id)
    if a is None:
        raise HTTPException(404, "attachment not found")
    return a


@viewer.get("/attachments/{attachment_id}")
def read(attachment_id: str) -> dict[str, Any]:
    """The extracted text the agent reads (first 50,000 characters)."""
    with session() as s:
        a = _get(s, attachment_id)
    return {**attachments.summary(a), "text": a.text[:50_000],
            "truncated": len(a.text) > 50_000}


@admin.delete("/attachments/{attachment_id}", status_code=204)
def remove(attachment_id: str) -> None:
    """Remove an upload, a schedule's file, or a file from a task that hasn't started."""
    with session() as s:
        a = _get(s, attachment_id)
        if a.task_id:
            task = s.get(Task, a.task_id)
            if task and task.status != TaskStatus.QUEUED:
                raise HTTPException(409, "the task has already used this file")
        s.delete(a)
        s.commit()


class KeepIn(BaseModel):
    title: str = Field(default="", max_length=200)


@admin.post("/attachments/{attachment_id}/keep", status_code=201)
async def keep(attachment_id: str, body: KeepIn) -> dict[str, Any]:
    """Copy an attachment into the knowledge library (it isn't attached to any agent)."""
    with session() as s:
        a = _get(s, attachment_id)
        title = body.title.strip() or a.filename.rsplit(".", 1)[0]
        if s.exec(select(KnowledgeDoc).where(KnowledgeDoc.title == title)).first():
            raise HTTPException(409, f"a knowledge document called {title!r} already exists")
        doc = KnowledgeDoc(title=title, source=a.filename, content=a.text)
        s.add(doc)
        s.commit()
    await knowledge.index_doc(doc.id)
    audit("knowledge_added", f"{title} (kept from task attachment {a.filename})",
          task_id=a.task_id)
    return {"id": doc.id, "title": doc.title}
