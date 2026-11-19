"""Runs agent graphs for tasks, turns graph output into board/3D updates, handles approvals."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from langgraph.types import Command
from sqlalchemy import func
from sqlmodel import select

from app import attachments, handoff, messages, notify, reporting, review, schedules
from app.agents import custom, registry
from app.db import AgentRun, Approval, Skill, Task, WorkflowLog, audit, session
from app.deps import Deps
from app.events.schema import (
    AgentEvent,
    AgentState,
    AgentStatus,
    ApprovalStatus,
    ApprovalUpdatedMsg,
    GovernorMsg,
    SnapshotMsg,
    TaskDeletedMsg,
    TaskStatus,
    TaskUpdatedMsg,
    Zone,
    utcnow,
)
from app.marketo.gateway import LiveMarketo
from app.workflows import ThreadOutcome
from app.workflows import registry as workflow_registry

log = logging.getLogger(__name__)

def _aware(dt: datetime | None) -> datetime | None:
    # SQLite drops tzinfo; everything we store is UTC.
    return dt.replace(tzinfo=UTC) if dt and dt.tzinfo is None else dt


class Hub:
    def __init__(self, deps: Deps, checkpointer, store=None):
        self.deps = deps
        self.graph = custom.build(checkpointer, store)  # shared by every configurable agent
        self.workflows = workflow_registry()  # code-defined graphs (app/workflows)
        self.workflow_graphs = {wid: spec.build(checkpointer, store)
                                for wid, spec in self.workflows.items()}
        self.statuses: dict[str, AgentStatus] = {}
        self.busy: dict[str, str] = {}  # agent_id -> task_id (running or awaiting approval)
        self.sync_roster()
        self._jobs: set[asyncio.Task] = set()
        self._task_jobs: dict[str, asyncio.Task] = {}  # running task -> its job (to cancel)
        self._loops: list[asyncio.Task] = []

    def sync_roster(self) -> None:
        """Track a status for every defined agent (after create / delete)."""
        defs = {d.id: d for d in registry.all_defs()}
        ids = set(defs)
        for agent_id in ids - set(self.statuses):  # idle agents wait in their home zone
            self.statuses[agent_id] = AgentStatus(
                agent_id=agent_id, zone=Zone(defs[agent_id].home_zone), state=AgentState.IDLE,
                status_text="Waiting for tasks")
        for agent_id, st in self.statuses.items():  # a new home zone applies while idle
            if agent_id in defs and st.state == AgentState.IDLE and agent_id not in self.busy:
                st.zone = Zone(defs[agent_id].home_zone)
        for agent_id in set(self.statuses) - ids - set(self.busy):
            del self.statuses[agent_id]

    async def roster_changed(self) -> None:
        self.sync_roster()
        await self.deps.bus.broadcast(self.snapshot())

    # --- lifecycle ------------------------------------------------------------------------

    def recover(self) -> None:
        """After a restart: restore each agent's last KPIs, fail half-finished runs, and
        re-attach runs paused for approval."""
        with session() as s:
            for agent_id in self.statuses:
                last = s.exec(select(AgentRun).where(AgentRun.agent_id == agent_id)
                              .order_by(AgentRun.finished_at.desc()).limit(1)).first()
                if last:
                    self.statuses[agent_id].metrics = dict(last.metrics)
            for t in s.exec(select(Task).where(Task.status == TaskStatus.IN_PROGRESS)):
                d = registry.get(t.agent_id)
                spec = self.workflows.get(workflow_for(t, d) or "") if d else None
                if spec and spec.resumable:  # it continues from where it stopped
                    t.status, t.result = TaskStatus.QUEUED, "Interrupted by a restart; resuming"
                else:
                    t.status, t.result = TaskStatus.FAILED, "Interrupted by restart"
                t.updated_at = utcnow()
                s.add(t)
            s.commit()
            for t in s.exec(select(Task).where(Task.status == TaskStatus.NEEDS_APPROVAL)):
                d = registry.get(t.agent_id)
                if not (d and workflow_for(t, d)):  # workflow runs aren't held while they wait
                    self.busy[t.agent_id] = t.id
                self.statuses[t.agent_id] = AgentStatus(
                    agent_id=t.agent_id, zone=Zone(d.home_zone) if d else Zone.BREAK_ROOM,
                    state=AgentState.NEEDS_HELP, status_text="Waiting for your approval",
                    task_id=t.id)

    def start_loops(self) -> None:
        self._loops = [asyncio.create_task(self._scheduler()),
                       asyncio.create_task(self._governor_ticker())]

    async def stop(self) -> None:
        for t in [*self._loops, *self._jobs]:
            t.cancel()
        await asyncio.gather(*self._loops, *self._jobs, return_exceptions=True)

    async def _scheduler(self) -> None:
        while True:
            try:
                for task in await asyncio.to_thread(schedules.due):  # recurring tasks
                    await self.deps.bus.broadcast(TaskUpdatedMsg(task=task.out()))
                await self._start_due_tasks()
                await self._expire_workflow_approvals()
            except Exception:
                log.exception("scheduler tick failed")
            await asyncio.sleep(2)

    async def _governor_ticker(self) -> None:
        while True:
            await self.deps.bus.broadcast(GovernorMsg(stats=self.deps.governor.stats()))
            await asyncio.sleep(2)

    async def _start_due_tasks(self) -> None:
        now = utcnow()
        with session() as s:
            # earliest due first: a scheduled task's time, or an ASAP task's creation
            queued = s.exec(select(Task).where(Task.status == TaskStatus.QUEUED,
                                               Task.archived_at.is_(None))
                            .order_by(func.coalesce(Task.scheduled_for, Task.created_at),
                                      Task.created_at)).all()
        if not queued:
            return
        defs = {d.id: d for d in registry.all_defs()}
        for task in queued:
            due = _aware(task.scheduled_for)
            d = defs.get(task.agent_id)
            if d is None or not d.enabled or task.agent_id in self.busy or (due and due > now):
                continue
            if (task.params or {}).get("after") and not await self._ready(task):
                continue
            self.busy[task.agent_id] = task.id
            await self._set_task(task.id, status=TaskStatus.IN_PROGRESS)
            audit("task_started", task.title, task_id=task.id, agent_id=task.agent_id)
            if (task.params or {}).get("from_agent_id") and not task.run:
                messages.add(task.id, d.id, d.name, "reply", "On it, starting now.")
            if workflow_for(task, d):
                self._track(task.id, self._run_workflow(task, d))
                continue
            files = attachments.for_task(task.id)
            brief = custom.brief_text(task.title, task.description, task.params)
            brief += earlier_results(task) + messages.notes_for_brief(task.id)
            if first := [a for a in files if a.round == 0]:
                brief += "\n\n" + attachments.brief_section(first)
            inputs = {"task_id": task.id, "agent_id": task.agent_id, "params": task.params,
                      "zone": self.statuses[task.agent_id].zone.value,
                      "config": {**registry.run_config(d), **task_overrides(task),
                                 "attachments": len(files)},
                      "brief": {"title": task.title, "description": task.description},
                      "messages": [{"role": "user", "content": brief}]}
            if feedback := pending_feedback(task):
                # a feedback round continues the task's own thread: the agent sees its
                # earlier work and the feedback, with a fresh step budget
                inputs["messages"] = [{"role": "user", "content": feedback}]
                inputs["thread_model_call_count"] = 0
            self._spawn(task.id, task.agent_id, inputs)

    def _spawn(self, task_id: str, agent_id: str, inputs: Any) -> None:
        self._track(task_id, self._drive(task_id, agent_id, inputs))

    def _track(self, task_id: str, coro) -> None:
        """Run a task's job, remembering it so the task can be cancelled."""
        job = asyncio.create_task(coro)
        self._jobs.add(job)
        self._task_jobs[task_id] = job

        def done(j: asyncio.Task) -> None:
            self._jobs.discard(j)
            if self._task_jobs.get(task_id) is j:
                del self._task_jobs[task_id]
        job.add_done_callback(done)

    async def _ready(self, task: Task) -> bool:
        """Whether a task that waits for others (`params.after`) may start. When they're
        all done, the agent who finished last walks over and hands it on (the relay on the
        floor), and the task starts a few seconds later. If one failed, so does this."""
        after = list(task.params.get("after") or [])
        with session() as s:
            prior = [s.get(Task, i) for i in after]
        failed = [p for p in prior if p is None or p.status == TaskStatus.FAILED]
        if failed:
            what = ", ".join(f"“{p.title}”" if p else "a deleted task" for p in failed)
            await self._set_task(task.id, status=TaskStatus.FAILED,
                                 result=f"Not started: it waits for {what}, which failed.")
            return False
        with session() as s:  # a rejection ("stop", not "request changes") stops the relay
            stopped = [p for p in prior if p.status == TaskStatus.DONE and (last_ := s.exec(
                select(Approval).where(Approval.task_id == p.id).order_by(
                    Approval.decided_at.desc())).first()) is not None
                and last_.status == ApprovalStatus.REJECTED
                and (last_.details or {}).get("choice") != "revise"]
        if stopped:
            what = ", ".join(f"“{p.title}”" for p in stopped)
            await self._set_task(task.id, status=TaskStatus.FAILED,
                                 result=f"Not started: you rejected {what}.")
            messages.add(task.id, messages.YOU, "You", "rejected",
                         f"Stopped here: {what} was rejected.")
            return False
        if any(p.status != TaskStatus.DONE for p in prior):
            return False
        if task.params.get("released"):
            return True
        last = max(prior, key=lambda p: _aware(p.updated_at))
        await self._set_task(task.id, params={**task.params, "released": True},
                             scheduled_for=utcnow() + timedelta(seconds=handoff.START_DELAY_S))
        if last.agent_id != task.agent_id and (st := self.statuses.get(last.agent_id)):
            await self.publish(handoff.event(task, st, sender_task_id=last.id))
        sender = registry.get(last.agent_id)
        messages.add(task.id, last.agent_id, sender.name if sender else last.agent_id,
                     "your_turn", f"Your turn: I've finished “{last.title}”.\n\n"
                     f"{(last.result or '').strip().split(chr(10) * 2)[0][:2000]}")
        return False

    async def cancel_tasks(self, task_ids: set[str]) -> None:
        """Stop running jobs for these tasks and free their agents."""
        jobs = [j for t, j in self._task_jobs.items() if t in task_ids]
        for j in jobs:
            j.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
        for agent_id, task_id in list(self.busy.items()):
            if task_id in task_ids:
                del self.busy[agent_id]

    # --- running a graph ------------------------------------------------------------------

    async def _drive(self, task_id: str, agent_id: str, inputs: Any) -> None:
        graph = self.graph
        with session() as s:
            task = s.get(Task, task_id)
        # the current run's thread: feedback rounds continue it, a requeued task starts anew
        config = {"configurable": {"thread_id": task.thread() if task else task_id}}
        try:
            interrupt = None
            # Drain the stream even after an interrupt: the paused checkpoint must be saved
            # before the approval exists, or a quick decision could resume a stale state.
            async for mode, chunk in graph.astream(inputs, config,
                                                   stream_mode=["custom", "updates"]):
                if mode == "custom":
                    await self.publish(AgentEvent.model_validate(chunk))
                elif "__interrupt__" in chunk:
                    interrupt = chunk["__interrupt__"][0].value
            if interrupt is not None:  # from HumanInTheLoopMiddleware
                review = await self._tool_review(graph, config, agent_id, interrupt)
                await self._on_interrupt(task_id, agent_id, review)
                return  # agent stays reserved until a human decides
            final = await graph.aget_state(config)
            result = final.values.get("result", "")
            if awaiting_reply(task_id):  # you sent work back: it answers you, not the board
                await self._ask_reply(task_id, agent_id, result)
                self.busy.pop(agent_id, None)
                return
            await self._set_task(task_id, status=TaskStatus.DONE, result=result)
            self._say_result(task_id, agent_id, result)
            self._record_run(task_id, agent_id, TaskStatus.DONE, result)
            reporting.record(agent_id, task_id, reporting.first_line(result), {})
            audit("task_done", result, task_id=task_id, agent_id=agent_id)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.exception("task %s failed", task_id)
            await self._set_task(task_id, status=TaskStatus.FAILED,
                                 result=f"{type(e).__name__}: {e}")
            self._record_run(task_id, agent_id, TaskStatus.FAILED, f"{type(e).__name__}: {e}")
            st = self.statuses[agent_id]
            await self.publish(AgentEvent(
                agent_id=agent_id, task_id=task_id, action="error", source_zone=st.zone,
                target_zone=st.zone, state=AgentState.ERROR, status_text=f"Failed: {e}"[:140],
                metrics=st.metrics))
            audit("task_failed", str(e), task_id=task_id, agent_id=agent_id)
            self._background(self._notify_failure(task_id, agent_id, f"{type(e).__name__}: {e}"))
        self.busy.pop(agent_id, None)

    def _say_result(self, task_id: str, agent_id: str, result: str) -> None:
        """The agent's closing message on the task: its whole report."""
        d = registry.get(agent_id)
        if (result or "").strip():
            messages.add(task_id, agent_id, d.name if d else agent_id, "result", result)

    def _background(self, coro) -> None:
        job = asyncio.create_task(coro)
        self._jobs.add(job)
        job.add_done_callback(self._jobs.discard)

    async def _notify_failure(self, task_id: str, agent_id: str, error: str) -> None:
        with session() as s:
            task = s.get(Task, task_id)
        d = registry.get(agent_id)
        await notify.task_failed(task_id, task.title if task else task_id,
                                 d.name if d else agent_id, error)

    def _record_run(self, task_id: str, agent_id: str, status: TaskStatus, result: str) -> None:
        with session() as s:
            s.add(AgentRun(task_id=task_id, agent_id=agent_id, status=status, result=result,
                           metrics=dict(self.statuses[agent_id].metrics)))
            s.commit()

    async def _on_interrupt(self, task_id: str, agent_id: str, payload: dict) -> None:
        with session() as s:
            approval = Approval(task_id=task_id, agent_id=agent_id, action=payload["action"],
                                summary=payload["summary"], details=payload.get("details", {}))
            s.add(approval)
            s.commit()
        await self._set_task(task_id, status=TaskStatus.NEEDS_APPROVAL)
        await self.deps.bus.broadcast(ApprovalUpdatedMsg(approval=approval.out()))
        st = self.statuses[agent_id]
        await self.publish(AgentEvent(
            agent_id=agent_id, task_id=task_id, action=payload["action"], source_zone=st.zone,
            target_zone=st.zone, state=AgentState.NEEDS_HELP, status_text="Needs your approval",
            metrics=st.metrics))
        audit("approval_requested", payload["summary"], task_id=task_id, agent_id=agent_id,
              data={"action": payload["action"]})
        d = registry.get(agent_id)
        self._background(notify.approval_requested(approval, d.name if d else agent_id))

    async def _ask_reply(self, task_id: str, agent_id: str, text: str) -> None:
        """The agent finished a turn after you sent work back, without asking again: it comes
        back to you with what it did or wants to know, and waits for your reply."""
        await self._set_task(task_id, result=text)
        self._say_result(task_id, agent_id, text)
        self._record_run(task_id, agent_id, TaskStatus.NEEDS_APPROVAL, text)
        reporting.record(agent_id, task_id, reporting.first_line(text), {})
        await self._on_interrupt(task_id, agent_id, {
            "action": "reply", "summary": text or "I've finished this round.",
            "details": {"kind": "reply"}})
        st = self.statuses[agent_id]
        await self.publish(AgentEvent(
            agent_id=agent_id, task_id=task_id, action="reply", source_zone=st.zone,
            target_zone=st.zone, state=AgentState.NEEDS_HELP, status_text="Wants your reply",
            metrics=st.metrics))

    async def _decide_reply(self, s, approval: Approval, approved: bool, comment: str,
                            via: str, choice: str | None) -> Approval:
        """Answer an agent that came back to you: reply (another round, same conversation)
        or accept what it has and close the task."""
        reply = choice == "reply" or (not approved and choice != "done")
        if reply and not comment.strip():
            raise ValueError("write your reply: it goes to the agent")
        approval.status = ApprovalStatus.APPROVED
        approval.comment, approval.decided_at = comment, utcnow()
        approval.details = {**approval.details, "choice": "reply" if reply else "done",
                            "sent_back": reply, "via": via}
        s.add(approval)
        task = s.get(Task, approval.task_id)
        if reply:
            add_feedback_round(task, comment)
        else:
            task.status, task.updated_at = TaskStatus.DONE, utcnow()
        s.add(task)
        s.commit()
        await self.deps.bus.broadcast(ApprovalUpdatedMsg(approval=approval.out()))
        audit("task_feedback" if reply else "task_done", comment or task.result,
              task_id=task.id, agent_id=approval.agent_id, data={"via": via})
        messages.add(task.id, messages.YOU, "You", "feedback" if reply else "approved",
                     comment.strip() if reply else
                     "Looks good: marked done." + (f" {comment}" if comment else ""))
        await self.task_changed(task)
        if not reply:
            self._record_run(task.id, approval.agent_id, TaskStatus.DONE, task.result)
            await self._agent_event(approval.agent_id, None, AgentState.IDLE, "Waiting for tasks",
                                    Zone.BREAK_ROOM)
        return approval

    async def _tool_review(self, graph, config, agent_id: str, request: dict) -> dict:
        """Turn a HumanInTheLoopMiddleware request into an approval card's payload."""
        actions = request["action_requests"]
        d = registry.get(agent_id)
        state = await graph.aget_state(config)
        # name what's being approved (with links and previews), not just tool calls and IDs
        what = await review.fill_in(review.items(
            state.values.get("task_id"), [{"tool": a["name"], "args": a["args"]}
                                          for a in actions]))
        summary = review.summary(d.name if d else agent_id, what)
        last = next((m for m in reversed(state.values.get("messages", []))
                     if getattr(m, "type", "") == "ai"), None)
        if last is not None and last.text:
            summary += f" Reasoning: {last.text[:400]}"
        toolset = state.values.get("toolset", {})
        return {"action": actions[0]["name"] if len(actions) == 1 else "tool_calls",
                "summary": summary,
                "details": {"items": what,
                            "calls": [{"tool": a["name"], "risk": toolset.get(a["name"], "write"),
                                       "args": a["args"]} for a in actions]}}

    async def decide(self, approval_id: str, approved: bool, comment: str,
                     edits: dict[int, dict[str, Any]] | None = None,
                     via: str = "app", choice: str | None = None,
                     selected: list[int] | None = None) -> Approval:
        """Record a decision and resume the run. `edits` replaces the arguments of tool
        calls (by position) before they run. `via` says where it was made (app, email link,
        email link) for the audit log. Workflow approvals take one of their own `choice`s.

        `selected` approves only some items (tool calls by position; a workflow's picks by
        ID). Items left out go back to the agent with your notes, like "revise" (send it all
        back): the agent works on them and asks again, or comes back with a reply."""
        with session() as s:
            approval = s.get(Approval, approval_id)
            if approval is None:
                raise KeyError(approval_id)
            if approval.status != ApprovalStatus.PENDING:
                raise ValueError(f"approval already {approval.status}")
            if approval.details.get("kind") == "reply":
                return await self._decide_reply(s, approval, approved, comment, via, choice)
            if approval.details.get("workflow"):
                return await self._decide_workflow(s, approval, approved, comment, via, choice,
                                                   edits, selected)
            calls = approval.details.get("calls", [])
            revise = choice == "revise"
            if revise and not comment.strip():
                raise ValueError("say what to change: your notes go to the agent")
            keep = set(range(len(calls))) if approved and not revise else set()
            if selected is not None and approved and not revise:
                if any(not 0 <= i < len(calls) for i in selected):
                    raise ValueError("selected items must be among the calls under review")
                keep = set(selected)
            if edits and any(i not in keep for i in edits):
                raise ValueError("edits apply only to approved tool calls")
            partial = bool(keep) and len(keep) < len(calls)
            sent_back = revise or (partial and bool(comment.strip()))
            approval.status = ApprovalStatus.APPROVED if keep else ApprovalStatus.REJECTED
            approval.comment, approval.decided_at = comment, utcnow()
            approval.details = {**approval.details, "sent_back": sent_back,
                                **({"choice": "revise"} if revise else {}),
                                **({"choice": "partial", "selected": sorted(keep)}
                                   if partial else {})}
            if edits:
                approval.details = {**approval.details, "calls": [
                    {**c, "edited_args": edits[i]} if i in edits else c
                    for i, c in enumerate(calls)]}
            s.add(approval)
            s.commit()
        await self.deps.bus.broadcast(ApprovalUpdatedMsg(approval=approval.out()))
        audit(f"approval_{approval.status}", comment or approval.summary,
              task_id=approval.task_id, agent_id=approval.agent_id,
              data={"action": approval.action, "via": via})
        await self._set_task(approval.task_id, status=TaskStatus.IN_PROGRESS)
        names = [review.item_name(it) for it in approval.details.get("items") or []]
        if len(names) != len(calls):
            names = [c["tool"] for c in calls]
        if revise:
            said = f"Changes requested: {comment}"
        elif partial:
            said = (f"Approved {', '.join(names[i] for i in sorted(keep))}. Not yet: "
                    f"{', '.join(n for i, n in enumerate(names) if i not in keep)}."
                    + (f" {comment}" if comment else ""))
        else:
            said = ("Approved." if keep else "Rejected.") + (f" {comment}" if comment else "")
        messages.add(approval.task_id, messages.YOU, "You",
                     "changes" if sent_back else "approved" if keep else "rejected", said)
        back = revise_note(comment, partial) if sent_back else None
        decisions = []
        for i, c in enumerate(calls):
            if i in keep:
                decisions.append({"type": "edit", "edited_action": {"name": c["tool"],
                                                                    "args": edits[i]}}
                                 if edits and i in edits else {"type": "approve"})
            elif back:
                decisions.append({"type": "reject", "message": back})
            elif keep:  # left out without notes: skip it
                decisions.append({"type": "reject", "message": "The reviewer left this one out: "
                                  "don't do it, and don't ask for it again."})
            else:
                decisions.append({"type": "reject", **({"message": comment} if comment else {})})
        self._spawn(approval.task_id, approval.agent_id, Command(
            resume={"decisions": decisions},
            # a fresh step budget for the revision
            **({"update": {"thread_model_call_count": 0}} if sent_back else {})))
        return approval

    # --- code-defined workflows (app/workflows) ---------------------------------------------

    async def _run_workflow(self, task: Task, d) -> None:
        wf = workflow_for(task, d)
        spec = self.workflows.get(wf)
        try:
            if spec is None:
                raise RuntimeError(f"unknown workflow {wf!r}")
            ctx = _WorkflowContext(self, task, d, wf)
            text, paused = await spec.run_batch(ctx)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.exception("workflow task %s failed", task.id)
            error = f"{type(e).__name__}: {e}"
            await self._set_task(task.id, status=TaskStatus.FAILED, result=error)
            self._record_run(task.id, d.id, TaskStatus.FAILED, error)
            audit("task_failed", error, task_id=task.id, agent_id=d.id)
            await self._agent_event(d.id, task.id, AgentState.ERROR, f"Failed: {e}"[:140])
            self._background(self._notify_failure(task.id, d.id, error))
            self.busy.pop(d.id, None)
            return
        status = TaskStatus.NEEDS_APPROVAL if paused else TaskStatus.DONE
        await self._set_task(task.id, status=status, result=text)
        self._say_result(task.id, d.id, text)
        self._record_run(task.id, d.id, status, text)
        audit("task_done" if not paused else "task_waiting", text.split("\n")[0],
              task_id=task.id, agent_id=d.id)
        self.busy.pop(d.id, None)  # free for the next batch even while a decision waits
        await self._settle_agent(d.id, task.id)

    async def _agent_event(self, agent_id: str, task_id: str | None, state: AgentState,
                           text: str, zone: Zone | None = None) -> None:
        st = self.statuses.get(agent_id)
        here = st.zone if st else Zone.BREAK_ROOM
        await self.publish(AgentEvent(
            agent_id=agent_id, task_id=task_id, action="status", source_zone=here,
            target_zone=zone or here, state=state, status_text=text,
            metrics=st.metrics if st else {}))

    def _pending_workflow_approvals(self, agent_id: str) -> list[Approval]:
        with session() as s:
            rows = s.exec(select(Approval).where(Approval.agent_id == agent_id,
                                                 Approval.status == ApprovalStatus.PENDING))
            return [a for a in rows if a.details.get("workflow")]

    async def _settle_agent(self, agent_id: str, task_id: str | None) -> None:
        """After a batch or a resume: back to HQ, flagged if workflow decisions are still open."""
        pending = self._pending_workflow_approvals(agent_id)
        if pending:
            await self._agent_event(agent_id, pending[0].task_id, AgentState.NEEDS_HELP,
                                    f"{len(pending)} decision(s) waiting", Zone.BREAK_ROOM)
        else:
            await self._agent_event(agent_id, None, AgentState.IDLE, "Waiting for tasks",
                                    Zone.BREAK_ROOM)

    async def _workflow_paused(self, task_id: str, d, spec, thread_id: str,
                               request: dict[str, Any]) -> str:
        card = request.get("card", {})
        lead = card.get("lead", {})
        who = " ".join(x for x in (lead.get("firstName"), lead.get("lastName")) if x) or \
            f"lead {request.get('lead_id')}"
        role = ", ".join(x for x in (lead.get("title"), lead.get("company")) if x)
        summary = request.get("summary") or (
            f"{d.name} needs your decision on {who}{f' ({role})' if role else ''}. "
            f"Nothing reaches Marketo until you decide.")
        cfg = {**(d.templates[0].get("params", {}) if d.templates else {})}
        details = {"workflow": spec.id, "thread_id": thread_id, "lead_id": request.get("lead_id"),
                   **({"pick": request["pick"]} if request.get("pick") else {}),
                   "choices": request.get("choices", ["approve", "reject"]),
                   "choice_labels": spec.choice_labels, "card": card,
                   "decision": request.get("decision", {}),
                   "timeout_hours": request.get("timeout_hours", 8),
                   "approver_email": cfg.get("approver_email", "")}
        with session() as s:
            approval = Approval(task_id=task_id, agent_id=d.id,
                                action=request.get("decision", {}).get("action", "approval"),
                                summary=summary, details=details)
            s.add(approval)
            s.commit()
        await self.deps.bus.broadcast(ApprovalUpdatedMsg(approval=approval.out()))
        audit("approval_requested", summary, task_id=task_id, agent_id=d.id,
              data={"action": approval.action, "thread_id": thread_id})
        self._background(notify.approval_requested(approval, d.name))
        return approval.id

    async def _decide_workflow(self, s, approval: Approval, approved: bool, comment: str,
                               via: str, choice: str | None, edits,
                               selected: list[int] | None = None) -> Approval:
        choices = approval.details.get("choices", [])
        choice = choice or ("approve" if approved else "reject")
        if edits or (choice not in choices and choice != "timeout"):
            raise ValueError(f"choose one of: {', '.join(choices)}")
        pick = approval.details.get("pick") or []
        if selected is not None and choice == "approve" and pick:
            offered = {int(p["id"]) for p in pick}
            if not set(selected) <= offered:
                raise ValueError("selected items must be among those offered")
            if not selected:
                keep_all = (approval.details.get("choice_labels") or {}).get("reject", "reject")
                raise ValueError(f"tick at least one, or choose “{keep_all}”")
        else:
            selected = None
        approval.status = (ApprovalStatus.APPROVED if choice in ("approve", "downgrade")
                           else ApprovalStatus.REJECTED)
        approval.comment, approval.decided_at = comment, utcnow()
        approval.details = {**approval.details, "choice": choice, "via": via,
                            **({"selected": selected} if selected is not None else {})}
        s.add(approval)
        s.commit()
        await self.deps.bus.broadcast(ApprovalUpdatedMsg(approval=approval.out()))
        audit(f"approval_{approval.status}", comment or f"{choice}: {approval.summary}",
              task_id=approval.task_id, agent_id=approval.agent_id,
              data={"action": approval.action, "via": via, "choice": choice})
        labels = approval.details.get("choice_labels") or {}
        said = f"{labels.get(choice, choice.title())}."
        if selected is not None and len(selected) < len(pick):
            chosen = set(selected)
            said = (f"{labels.get(choice, choice.title())}: "
                    f"{', '.join(p['label'] for p in pick if int(p['id']) in chosen)}. Keep "
                    f"{', '.join(p['label'] for p in pick if int(p['id']) not in chosen)}.")
        messages.add(approval.task_id, messages.YOU, "You", "approved" if approval.status ==
                     ApprovalStatus.APPROVED else "rejected",
                     said + (f" {comment}" if comment else ""))
        approver = (approval.details.get("approver_email") or via) if via != "app" \
            else "hub admin"
        self._background(self._resume_workflow(approval, choice, approver, comment))
        return approval

    async def _resume_workflow(self, approval: Approval, choice: str, approver: str,
                               note: str) -> None:
        spec = self.workflows[approval.details["workflow"]]
        d = registry.get(approval.agent_id)
        with session() as s:
            task = s.get(Task, approval.task_id)
        if task is None or d is None:
            log.warning("can't resume %s: task or agent is gone", approval.id)
            return
        ctx = _WorkflowContext(self, task, d, approval.details["workflow"])
        thread_id = approval.details["thread_id"]
        try:
            value = spec.resume_value(choice, approver, note)
            if "selected" in approval.details and isinstance(value, dict):
                value = {**value, "selected": approval.details["selected"]}
            outcome = await ctx.stream(thread_id, Command(resume=value))
            line = await spec.after_resume(ctx, thread_id, outcome)
            self._say_result(approval.task_id, approval.agent_id, line)
        except Exception as e:
            log.exception("resuming %s failed", thread_id)
            line = f"Resuming {thread_id} failed: {type(e).__name__}: {e}"
            ctx.log(thread_id=thread_id, item_id=str(approval.details.get("lead_id", "")),
                    status="ERROR", summary=line[:400])
        with session() as s:
            task = s.get(Task, approval.task_id)
            open_ = [a for a in s.exec(select(Approval).where(
                Approval.task_id == approval.task_id,
                Approval.status == ApprovalStatus.PENDING))]
        result = f"{task.result}\n\n{line}" if task and task.result else line
        status = TaskStatus.NEEDS_APPROVAL if open_ else TaskStatus.DONE
        await self._set_task(approval.task_id, status=status, result=result)
        audit("approval_resumed", line, task_id=approval.task_id, agent_id=approval.agent_id)
        await self._settle_agent(approval.agent_id, approval.task_id)

    async def _expire_workflow_approvals(self) -> None:
        """A workflow request nobody answered in time is decided as "timeout"."""
        now = utcnow()
        with session() as s:
            pending = s.exec(select(Approval).where(
                Approval.status == ApprovalStatus.PENDING)).all()
        for a in pending:
            hours = a.details.get("timeout_hours")
            if a.details.get("workflow") and hours and \
                    (now - _aware(a.created_at)).total_seconds() > float(hours) * 3600:
                try:
                    await self.decide(a.id, False, f"No decision within {hours} h",
                                      via="timeout", choice="timeout")
                except ValueError:
                    pass  # decided meanwhile

    # --- state + broadcasting -------------------------------------------------------------

    async def publish(self, event: AgentEvent) -> None:
        st = self.statuses.setdefault(event.agent_id, AgentStatus(
            agent_id=event.agent_id, zone=event.source_zone, state=event.state,
            status_text=event.status_text))
        # For TRAVELING this is the destination, which is where a reconnecting client should
        # place the agent.
        st.zone = event.target_zone
        st.state, st.status_text, st.task_id = event.state, event.status_text, event.task_id
        st.metrics = {**st.metrics, **event.metrics}
        await self.deps.bus.broadcast(event)

    async def _set_task(self, task_id: str, **fields: Any) -> Task | None:
        with session() as s:
            task = s.get(Task, task_id)
            if task is None:
                return None
            for k, v in fields.items():
                setattr(task, k, v)
            task.updated_at = utcnow()
            s.add(task)
            s.commit()
        await self.deps.bus.broadcast(TaskUpdatedMsg(task=task.out()))
        return task

    async def task_changed(self, task: Task) -> None:
        await self.deps.bus.broadcast(TaskUpdatedMsg(task=task.out()))

    async def task_deleted(self, task_id: str) -> None:
        await self.deps.bus.broadcast(TaskDeletedMsg(task_id=task_id))

    def snapshot(self) -> SnapshotMsg:
        with session() as s:
            tasks = [t.out() for t in s.exec(select(Task).order_by(Task.created_at))]
            approvals = [a.out() for a in s.exec(select(Approval).order_by(Approval.created_at))]
        return SnapshotMsg(agents=registry.profiles(), statuses=list(self.statuses.values()),
                           tasks=tasks, approvals=approvals, governor=self.deps.governor.stats(),
                           marketo_mode="live" if isinstance(self.deps.marketo, LiveMarketo)
                           else "demo")



AUTONOMY = ("approve_writes", "approve_destructive", "autonomous")


def task_overrides(task: Task) -> dict[str, Any]:
    """Run config a task may set for itself: its approval level (e.g. builders that
    draft freely and ask before approving or activating anything)."""
    autonomy = (task.params or {}).get("autonomy")
    return {"autonomy": autonomy} if autonomy in AUTONOMY else {}


def earlier_results(task: Task, chars: int = 8000) -> str:
    """The results of the tasks this one waited for, and of the ones those waited for, all
    the way back (a report at the end of a plan sees everyone's work), oldest first."""
    seen: dict[str, Task] = {}
    todo = list((task.params or {}).get("after") or [])
    with session() as s:
        while todo:
            i = todo.pop()
            if i in seen or (t := s.get(Task, i)) is None:
                continue
            seen[i] = t
            todo += (t.params or {}).get("after") or []
    if not seen:
        return ""
    names = {d.id: d.name for d in registry.all_defs()}
    prior = sorted(seen.values(), key=lambda t: _aware(t.updated_at))
    parts = [f"### {t.title} ({names.get(t.agent_id, t.agent_id)}, {t.status.value})\n\n"
             + ((t.result or "(no result)")[:chars]
                + (" … (shortened)" if len(t.result or "") > chars else ""))
             for t in prior]
    return "\n\nResults from the earlier tasks:\n\n" + "\n\n".join(parts)


def pending_feedback(task: Task) -> str:
    """The message for a feedback round the task was re-queued with, if any."""
    revisions = (task.params or {}).get("revisions") or []
    if not revisions or revisions[-1].get("started"):
        return ""
    n = len(revisions)
    with session() as s:  # mark it taken, so a restart doesn't replay it as new
        t = s.get(Task, task.id)
        params = dict(t.params)
        params["revisions"] = [*revisions[:-1], {**revisions[-1], "started": True}]
        t.params = params
        s.add(t)
        s.commit()
    added = attachments.brief_section(attachments.for_task(task.id, round=n),
                                      "Attached with this feedback")
    return (f"Feedback round {n} from the reviewer:\n\n{revisions[-1]['feedback']}\n\n"
            + (added + "\n\n" if added else "")
            + "Address it. If it asks for changes, make them: save each changed deliverable "
            "again with the same kind and name (that adds a new version), re-run the brand "
            "check until it passes, re-publish drafts you changed, and ask for approval again "
            "for anything that needs it. If it's a question, answer it. Finish with a short "
            "summary of what you changed, or your answer.")


def revise_note(comment: str, partial: bool) -> str:
    """What the agent hears for work you sent back with notes."""
    head = ("The reviewer approved the other items, but not this one yet:" if partial else
            "The reviewer looked at this and wants changes before approving:")
    return (f"{head}\n\n{comment.strip()}\n\nThis isn't a no: keep going. Revise your work to "
            "address these notes (save changed designs again with the same kind and name, and "
            "re-publish the drafts), then ask for approval again. If you have a question, or "
            "you believe nothing needs to change, say so briefly in your reply: the reviewer "
            "will answer you.")


def awaiting_reply(task_id: str) -> bool:
    """Whether the task's latest approval sent work back (notes, or a reply to the agent):
    then the agent's next answer goes to you, not straight to "done"."""
    with session() as s:
        last = s.exec(select(Approval).where(Approval.task_id == task_id)
                      .order_by(Approval.created_at.desc())).first()
    return bool(last and last.status != ApprovalStatus.PENDING
                and (last.details or {}).get("sent_back"))


def add_feedback_round(task: Task, text: str) -> int:
    """Queue another round of a task with your words: the agent continues its own thread.
    The caller adds the task to its session and commits."""
    params = dict(task.params or {})
    params["revisions"] = [*(params.get("revisions") or []),
                           {"feedback": text.strip(), "at": utcnow().isoformat()}]
    task.params, task.status, task.scheduled_for = params, TaskStatus.QUEUED, None
    task.updated_at = utcnow()
    return len(params["revisions"])


def workflow_for(task: Task, d) -> str:
    """The workflow a task runs: the agent's own, or one its task templates name (so an
    ordinary agent can offer a workflow task). "" = the agent's configurable loop."""
    wanted = (task.params or {}).get("workflow") or d.workflow
    if not wanted:
        return ""
    allowed = {d.workflow} | {(t.get("params") or {}).get("workflow") for t in d.templates}
    return wanted if wanted in allowed else ""


class _WorkflowContext:
    """BatchContext for one task: streams workflow threads through the hub."""

    def __init__(self, hub: "Hub", task: Task, d, workflow: str):
        self.hub, self._task, self._def = hub, task, d
        self.task_id, self.agent_id, self.agent_name = task.id, d.id, d.name
        self.run_key = task.thread()  # task id, plus the run when it was requeued
        self.enabled, self.model_tier = d.enabled, d.model_tier
        self.knowledge_ids = list(d.knowledge_ids)
        with session() as s:
            self.skill_names = [k.name for k in s.exec(select(Skill).where(
                Skill.id.in_(list(d.skill_ids) or [""])))]
        # the agent's template for this workflow supplies the defaults
        template = next((t for t in d.templates
                         if (t.get("params") or {}).get("workflow", d.workflow) == workflow),
                        None)
        self.template_params = dict((template or {}).get("params", {}))
        self.task_params = dict(task.params or {})
        self.spec = hub.workflows[workflow]
        self.graph = hub.workflow_graphs[workflow]

    async def stream(self, thread_id: str, inputs: Any) -> ThreadOutcome:
        if isinstance(inputs, dict):
            st = self.hub.statuses.get(self.agent_id)
            inputs = {"zone": (st.zone if st else Zone.BREAK_ROOM).value, **inputs}
        config = {"configurable": {"thread_id": thread_id}}
        interrupt = None
        async for mode, chunk in self.graph.astream(inputs, config,
                                                    stream_mode=["custom", "updates"]):
            if mode == "custom":
                await self.hub.publish(AgentEvent.model_validate(chunk))
            elif "__interrupt__" in chunk:
                interrupt = chunk["__interrupt__"][0].value
        values = (await self.graph.aget_state(config)).values
        if interrupt is not None:
            return ThreadOutcome("interrupted", values, interrupt)
        return ThreadOutcome("done", values)

    async def state(self, thread_id: str) -> dict[str, Any]:
        snap = await self.graph.aget_state({"configurable": {"thread_id": thread_id}})
        return dict(snap.values or {})

    async def pause(self, thread_id: str, request: dict[str, Any]) -> str:
        return await self.hub._workflow_paused(self.task_id, self._def, self.spec, thread_id,
                                               request)

    def log(self, **row: Any) -> None:
        with session() as s:
            s.add(WorkflowLog(workflow=self.spec.id, run_id=self.task_id, **row))
            s.commit()

    def report(self, headline: str, kpis: dict[str, Any]) -> None:
        reporting.record(self.agent_id, self.task_id, headline, kpis)

    async def hand_off(self, to: str, title: str, brief: str,
                       lead_ids: list[int] | None = None) -> Task:
        task = await asyncio.to_thread(
            handoff.create, from_task_id=self.task_id, from_agent_id=self.agent_id, to=to,
            title=title, brief=brief, lead_ids=lead_ids)
        await self.hub.task_changed(task)
        st = self.hub.statuses.get(self.agent_id)
        if st is not None:
            await self.hub.publish(handoff.event(task, st))
        return task
