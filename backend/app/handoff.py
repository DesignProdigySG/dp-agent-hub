"""Agents handing work to each other: one agent creates a task for another.

The new task carries a note, the leads or files it's about, and who it came from
(`params.from_agent_id` / `from_task_id`). It starts a few seconds later, so the hand-off
plays out on the floor first: an AgentEvent with action "handoff" sends the sender over to
the receiver, and the two exchange a line. Hops are counted so two agents can't bounce a
task between them forever.

Custom agents hand off with the `hand_off` tool (agents/tools.py); workflows through
`BatchContext.hand_off`. Both end here.
"""

import logging
import re
from datetime import timedelta
from typing import Any

from sqlmodel import select

from app.agents import registry
from app.db import AgentDef, Task, TaskAttachment, audit, session
from app.events.schema import AgentEvent, AgentState, AgentStatus, Handoff, utcnow
from app.marketo import links

log = logging.getLogger(__name__)

MAX_HOPS = 3
START_DELAY_S = 8  # the receiver starts after the two have met on the floor
LINE_CHARS = 40
MAX_LEADS = 500


class HandoffError(ValueError):
    pass


def resolve(to: str) -> AgentDef | None:
    """An agent by id, or by name (case-insensitive)."""
    to = to.strip()
    if d := registry.get(to):
        return d
    low = to.lower()
    return next((d for d in registry.all_defs() if d.name.lower() == low
                 or d.id == low.replace(" ", "_")), None)


def _short(text: str, limit: int = LINE_CHARS) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0] if " " in text[:limit] else text[:limit - 1]
    return cut.rstrip(" ,;:") + "…"


def lines(task: Task) -> tuple[str, str]:
    """The two scripted lines of the exchange: what the sender says, and the reply."""
    from app.reporting import first_line

    n = len((task.params or {}).get("lead_ids") or [])
    said = first_line(task.description) or task.title
    if n and len(said) > LINE_CHARS:
        said = f"{n} leads ready for you"
    return _short(said), "On it"


def create(*, from_task_id: str | None, from_agent_id: str, to: str, title: str, brief: str,
           lead_ids: list[int] | None = None, attachment_ids: list[str] | None = None,
           params: dict[str, Any] | None = None, delay_s: int = START_DELAY_S,
           allow_self: bool = False) -> Task:
    """The receiver's task. Raises HandoffError with a message the sender can act on.
    `params` are added to the task's own (e.g. `after`: tasks it waits for); `shared`
    (context for a whole piece of work, like the IDs of the program being built) is passed down."""
    sender = registry.get(from_agent_id)
    receiver = resolve(to)
    if receiver is None:
        team = ", ".join(f"{d.name} ({d.id})" for d in registry.all_defs() if d.enabled
                         and d.id != from_agent_id)
        raise HandoffError(f"no agent named {to!r}. The team: {team or 'nobody else'}")
    if receiver.id == from_agent_id and not allow_self:  # a plan may end with the planner
        raise HandoffError("you can't hand work to yourself")
    if not receiver.enabled:
        raise HandoffError(f"{receiver.name} is disabled")
    title = (title or "").strip()[:200] or f"From {sender.name if sender else from_agent_id}"
    ids = list(dict.fromkeys(int(i) for i in (lead_ids or [])))[:MAX_LEADS]
    with session() as s:
        origin = s.get(Task, from_task_id) if from_task_id else None
        hops = int(((origin.params if origin else None) or {}).get("hops", 0)) + 1
        if hops > MAX_HOPS:
            raise HandoffError(f"this work has already been handed on {hops - 1} times; "
                               "finish it or report back instead")
        description = (brief or "").strip()
        if ids:
            description += "\n\nLeads:\n" + "\n".join(
                f"- [{i}]({u})" if (u := links.url("lead", i)) else f"- {i}" for i in ids)
        note = f"Handed off by {sender.name if sender else from_agent_id}" + (
            f" from task {origin.id} ({origin.title})" if origin else "")
        task = Task(
            title=title, description=description, agent_id=receiver.id,
            params={"from_task_id": origin.id if origin else None,
                    "from_agent_id": from_agent_id,
                    "from_agent_name": sender.name if sender else from_agent_id,
                    "to_agent_name": receiver.name, "hops": hops,
                    **({"lead_ids": ids} if ids else {}),
                    **({"shared": origin.params["shared"]} if origin and
                       (origin.params or {}).get("shared") else {}),
                    **(params or {})},
            scheduled_for=utcnow() + timedelta(seconds=delay_s),
            history=[{"run": 0, "status": "handed_off", "result": note,
                      "at": utcnow().isoformat()}])
        s.add(task)
        copied = []
        wanted = set(attachment_ids or [])
        if wanted and origin:
            for a in s.exec(select(TaskAttachment).where(TaskAttachment.task_id == origin.id)):
                if a.id in wanted or a.filename in wanted:
                    s.add(TaskAttachment(task_id=task.id, filename=a.filename, mime=a.mime,
                                         size=a.size, text=a.text))
                    copied.append(a.filename)
        s.commit()
    audit("task_created", f"{note}" + (f"; files: {', '.join(copied)}" if copied else ""),
          task_id=task.id, agent_id=receiver.id)
    from app import messages

    who = sender.name if sender else from_agent_id
    messages.add(task.id, from_agent_id, who, "handoff", f"**{title}**\n\n{description}")
    if origin and origin.id != task.id:
        messages.add(origin.id, from_agent_id, who, "handed_on",
                     f"Handed “{title}” to {receiver.name}.")
    log.info("%s handed task %s to %s", from_agent_id, task.id, receiver.id)
    return task


def event(task: Task, sender: AgentStatus, sender_task_id: str | None = None) -> AgentEvent:
    """The floor event: the sender stays where it is and goes to talk to the receiver. A
    sender whose own task is finished (the relay to the next step) stays idle: the walk and
    the conversation come from the event's hand-off, not its state."""
    line_from, line_to = lines(task)
    idle = sender.state == AgentState.IDLE
    return AgentEvent(
        agent_id=sender.agent_id, task_id=sender_task_id or sender.task_id, action="handoff",
        source_zone=sender.zone, target_zone=sender.zone,
        state=AgentState.IDLE if idle else AgentState.BUSY,
        status_text=sender.status_text if idle else
        f"Handing off to {task.params.get('to_agent_name', task.agent_id)}",
        metrics=sender.metrics,
        handoff=Handoff(to_agent_id=task.agent_id, task_id=task.id, line_from=line_from,
                        line_to=line_to))


def tool_result(task: Task) -> dict[str, Any]:
    """What the sending agent is told (it should cite the confirmation line)."""
    return {"task_id": task.id, "agent": task.params.get("to_agent_name"),
            "starts": f"in about {START_DELAY_S} seconds",
            "confirmation": f"Handed off to {task.params.get('to_agent_name')}: task "
                            f"{task.id} “{task.title}”"}
