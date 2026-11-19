"""The conversation on a task: who said what about it, people and agents alike.

Written where it happens: a hand-off (the brief on the receiver's task, a note on the
sender's), the relay ("your turn"), an agent picking work up ("on it"), your approvals,
change requests and rejections, feedback rounds, and notes you post. Notes left on a task
that hasn't started yet go into its brief.
"""

from typing import Any

from sqlmodel import select

from app.db import TaskMessage, session

YOU = "you"


def add(task_id: str, author_id: str, author_name: str, kind: str, text: str) -> TaskMessage:
    m = TaskMessage(task_id=task_id, author_id=author_id, author_name=author_name, kind=kind,
                    text=text.strip()[:8000])
    with session() as s:
        s.add(m)
        s.commit()
        s.refresh(m)
    return m


def out(m: TaskMessage) -> dict[str, Any]:
    return {"id": m.id, "task_id": m.task_id, "author_id": m.author_id,
            "author_name": m.author_name, "kind": m.kind, "text": m.text,
            "created_at": m.created_at.isoformat()}


def for_task(task_id: str) -> list[dict[str, Any]]:
    with session() as s:
        return [out(m) for m in s.exec(select(TaskMessage).where(TaskMessage.task_id == task_id)
                                       .order_by(TaskMessage.created_at, TaskMessage.id))]


def notes_for_brief(task_id: str) -> str:
    """Your notes on a task, for the agent's brief when it starts."""
    notes = [m for m in for_task(task_id) if m["author_id"] == YOU and m["kind"] == "note"]
    if not notes:
        return ""
    return "\n\nNotes from the requester on this task:\n" + "\n".join(
        f"- {m['text']}" for m in notes)
