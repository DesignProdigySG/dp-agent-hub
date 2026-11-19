"""Recurring tasks: next-run maths, no pile-ups, the API, and the hub running them."""

from datetime import UTC, datetime, timedelta

import pytest

from app.schedules import ScheduleIn, describe, next_run
from tests.conftest import make_agent, wait_for


def at(*a):
    return datetime(*a, tzinfo=UTC)


def test_daily_keeps_local_time_across_daylight_saving():
    s = ScheduleIn(agent_id="a", title="t", kind="daily", at_time="08:00", tz="America/New_York")
    # 08:00 New York is 12:00 UTC before the US change on 1 Nov 2026, 13:00 UTC after it
    assert next_run(s, at(2026, 10, 30, 0, 0)) == at(2026, 10, 30, 12, 0)
    assert next_run(s, at(2026, 10, 30, 12, 0)) == at(2026, 10, 31, 12, 0)  # strictly after
    assert next_run(s, at(2026, 11, 1, 20, 0)) == at(2026, 11, 2, 13, 0)


def test_weekly_and_interval():
    s = ScheduleIn(agent_id="a", title="t", kind="weekly", weekdays=[0, 3], at_time="09:30",
                   tz="Asia/Bangkok")
    # Thursday 5 Nov 2026 10:00 Bangkok has passed 09:30, so the next run is Monday 9 Nov
    assert next_run(s, at(2026, 11, 5, 3, 0)) == at(2026, 11, 9, 2, 30)
    assert describe(s) == "Weekly on Mon, Thu at 09:30 (Asia/Bangkok)"
    i = ScheduleIn(agent_id="a", title="t", kind="interval", every_minutes=15)
    assert next_run(i, at(2026, 11, 5, 3, 0)) == at(2026, 11, 5, 3, 15)
    assert describe(i) == "Every 15 minutes"


@pytest.mark.parametrize("bad", [{"every_minutes": 2, "kind": "interval"},
                                 {"at_time": "25:00"}, {"tz": "Mars/Base"},
                                 {"kind": "weekly", "weekdays": []}])
def test_validation(bad):
    with pytest.raises(ValueError):
        ScheduleIn(agent_id="a", title="t", **bad)


def test_no_pile_ups_but_approvals_dont_block(db):
    from app import schedules
    from app.db import Schedule, Task, session
    from app.events.schema import TaskStatus

    s = Schedule(agent_id="a", title="Every 15", kind="interval", every_minutes=15,
                 next_run_at=at(2026, 11, 5, 3, 0))
    with session() as x:
        x.add(s)
        x.commit()
    [first] = schedules.due(at(2026, 11, 5, 3, 0))
    assert first.schedule_id == s.id
    assert schedules.due(at(2026, 11, 5, 3, 16)) == []  # first is still queued: skipped
    with session() as x:
        sched = x.get(Schedule, s.id)
        assert "still queued" in sched.last_note
        assert sched.next_run_at.replace(tzinfo=UTC) == at(2026, 11, 5, 3, 31)
        t = x.get(Task, first.id)
        t.status = TaskStatus.NEEDS_APPROVAL  # waiting on a person doesn't block
        x.add(t)
        x.commit()
    assert len(schedules.due(at(2026, 11, 5, 3, 31))) == 1


def test_api_and_the_hub_runs_due_schedules(client, script):
    agent = make_agent(client)
    r = client.post("/api/schedules", json={"agent_id": agent["id"], "title": "Hourly check",
                                            "kind": "interval", "every_minutes": 60})
    assert r.status_code == 201, r.text
    sched = r.json()
    assert sched["description_text"] == "Every 1 hour(s)" and len(sched["upcoming"]) == 5
    assert client.post("/api/schedules", json={"agent_id": "nobody", "title": "x"}).status_code \
        == 422

    # make it due now; the hub's scheduler creates and runs the task
    from app.db import Schedule, session
    with session() as x:
        s = x.get(Schedule, sched["id"])
        s.next_run_at = datetime.now(UTC) - timedelta(seconds=1)
        x.add(s)
        x.commit()
    deadline_task = None
    for _ in range(100):
        tasks = [t for t in client.get("/api/tasks").json() if t["schedule_id"] == sched["id"]]
        if tasks:
            deadline_task = tasks[0]
            break
        import time
        time.sleep(0.1)
    assert deadline_task, "the scheduler didn't create a task"
    assert wait_for(client, deadline_task["id"], {"done", "failed"})["status"] == "done"

    # run now queues another; pausing and deleting work
    assert client.post(f"/api/schedules/{sched['id']}/run").status_code == 200
    paused = client.put(f"/api/schedules/{sched['id']}", json={
        **{k: sched[k] for k in ("agent_id", "title", "kind", "every_minutes", "tz")},
        "enabled": False}).json()
    assert paused["upcoming"] == []
    assert client.delete(f"/api/schedules/{sched['id']}").status_code == 204
