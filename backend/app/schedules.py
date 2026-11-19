"""Recurring tasks: a schedule creates an ordinary task at each occurrence.

Kinds: `interval` (every N minutes, N >= 5), `daily` (at HH:MM) and `weekly` (on some
weekdays at HH:MM), all in the schedule's own IANA timezone, so 08:00 stays 08:00 across
daylight-saving changes. Occurrences never pile up: if the schedule's previous task is still
queued or running, that occurrence is skipped (and noted). A task waiting on an approval
doesn't block the next one.
"""

import re
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlmodel import select

from app import attachments
from app.db import Schedule, Task, TaskAttachment, audit, session
from app.events.schema import TaskStatus, utcnow

MIN_INTERVAL = 5
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
BLOCKING = (TaskStatus.QUEUED, TaskStatus.IN_PROGRESS)


class ScheduleIn(BaseModel):
    agent_id: str
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    params: dict[str, Any] = Field(default_factory=dict)
    kind: Literal["interval", "daily", "weekly"] = "daily"
    every_minutes: int = Field(default=60, ge=MIN_INTERVAL, le=7 * 24 * 60)
    at_time: str = "08:00"
    weekdays: list[int] = Field(default_factory=list)
    tz: str = "UTC"
    enabled: bool = True
    attachment_ids: list[str] = Field(default_factory=list, max_length=20)  # added files

    @field_validator("at_time")
    @classmethod
    def _time(cls, v: str) -> str:
        m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", v.strip())
        if not m:
            raise ValueError("use HH:MM, e.g. 08:00")
        return f"{int(m.group(1)):02d}:{m.group(2)}"

    @field_validator("tz")
    @classmethod
    def _tz(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"unknown timezone {v!r}") from None
        return v

    @model_validator(mode="after")
    def _days(self) -> "ScheduleIn":
        self.weekdays = sorted(set(self.weekdays))
        if any(not 0 <= d <= 6 for d in self.weekdays):
            raise ValueError("weekdays are 0 (Monday) to 6 (Sunday)")
        if self.kind == "weekly" and not self.weekdays:
            raise ValueError("pick at least one weekday")
        return self


def next_run(s: Schedule | ScheduleIn, after: datetime) -> datetime:
    """The first occurrence strictly after `after` (UTC in, UTC out)."""
    after = after.astimezone(UTC)
    if s.kind == "interval":
        return after + timedelta(minutes=s.every_minutes)
    tz = ZoneInfo(s.tz)
    hour, minute = map(int, s.at_time.split(":"))
    local = after.astimezone(tz)
    for days in range(0, 8):
        day = (local + timedelta(days=days)).date()
        if s.kind == "weekly" and day.weekday() not in s.weekdays:
            continue
        at = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)
        if at.astimezone(UTC) > after:
            return at.astimezone(UTC)
    raise ValueError("no occurrence within a week")  # unreachable for valid schedules


def upcoming(s: Schedule, n: int = 5) -> list[datetime]:
    if not s.enabled or s.next_run_at is None:
        return []
    out = [_aware(s.next_run_at).astimezone(UTC)]
    while len(out) < n:
        out.append(next_run(s, out[-1]))
    return out


def describe(s: Schedule | ScheduleIn) -> str:
    if s.kind == "interval":
        m = s.every_minutes
        every = (f"{m // 1440} day(s)" if m % 1440 == 0 else f"{m // 60} hour(s)"
                 if m % 60 == 0 else f"{m} minutes")
        return f"Every {every}"
    if s.kind == "daily":
        return f"Daily at {s.at_time} ({s.tz})"
    days = ", ".join(DAYS[d] for d in s.weekdays)
    return f"Weekly on {days} at {s.at_time} ({s.tz})"


def out(s: Schedule) -> dict[str, Any]:
    with session() as db:
        files = [attachments.summary(a) for a in db.exec(
            select(TaskAttachment).where(TaskAttachment.schedule_id == s.id))]
    return {**s.model_dump(mode="json"), "description_text": describe(s),
            "upcoming": [t.isoformat() for t in upcoming(s)],
            "attachments": [{**f, "created_at": f["created_at"].isoformat()} for f in files]}


def _aware(dt: datetime | None) -> datetime | None:
    # SQLite returns naive datetimes; everything stored is UTC.
    return dt.replace(tzinfo=UTC) if dt and dt.tzinfo is None else dt


def due(now: datetime | None = None) -> list[Task]:
    """Create the tasks for every schedule that is due; returns them (already committed)."""
    now = now or utcnow()
    created: list[Task] = []
    notes: list[tuple] = []  # audit entries, written after the commit (one writer at a time)
    with session() as db:
        rows = [s for s in db.exec(select(Schedule).where(Schedule.enabled == True))  # noqa: E712
                if s.next_run_at and _aware(s.next_run_at) <= now]
        for s in rows:
            prev = db.get(Task, s.last_task_id) if s.last_task_id else None
            if prev is not None and prev.status in BLOCKING:
                s.last_note = (f"Skipped {now:%Y-%m-%d %H:%M} UTC: the previous run was "
                               f"still {prev.status.value.replace('_', ' ')}")
                notes.append(("schedule_skipped", f"{s.title}: {s.last_note}", s.agent_id,
                              prev.id, {"schedule_id": s.id}))
            else:
                task = Task(title=s.title, description=s.description, agent_id=s.agent_id,
                            params=dict(s.params), schedule_id=s.id)
                db.add(task)
                attachments.copy_to_task(s.id, task.id, db)
                s.last_run_at, s.last_task_id, s.last_note = now, task.id, ""
                created.append(task)
                notes.append(("task_created", f"{s.title} (schedule: {describe(s)})",
                              s.agent_id, task.id, {"schedule_id": s.id}))
            s.next_run_at = next_run(s, max(now, _aware(s.next_run_at) or now))
            s.updated_at = now
            db.add(s)
        db.commit()
    for kind, message, agent_id, task_id, data in notes:
        audit(kind, message, agent_id=agent_id, task_id=task_id, data=data)
    return created
