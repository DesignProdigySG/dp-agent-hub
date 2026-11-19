"""The standard agent report: KPIs declared by workflows, compared with a week earlier."""

from datetime import timedelta

from app import reporting
from app.events.schema import utcnow
from app.workflows.data_health.runner import scan_report
from tests.conftest import make_agent, wait_for


def _scan_kpis(overall, contact, total=738, unreachable=261, dups=3):
    dims = {d: {"avg": 70.0} for d in ("uniqueness", "completeness", "normalization",
                                       "accuracy", "recency", "engagement")}
    dims |= {"overall": {"avg": overall}, "contactability": {"avg": contact}}
    return {"total": total, "dimensions": dims,
            "contactability": {"unreachable_email": unreachable, "usable": 478},
            "duplicates": {"redundant": dups, "groups": dups},
            "engagement_levels": {"dormant": 718}}


def doctor(client):
    from app.agents import registry

    make_agent(client, id="data_doctor", name="Data Doctor", tools=["rest_get_leads"],
               templates=[{"title": "Full data health scan",
                           "params": {"workflow": "data_health_scan"}}])
    return registry.get("data_doctor")


def test_scan_report_headline_and_values():
    headline, values = scan_report(_scan_kpis(68.0, 47.0))
    assert headline == ("Scanned 738 leads: health 68/100, 261 can't be emailed, "
                        "3 duplicate group(s), 718 with no engagement.")
    assert values["overall"] == 68.0 and values["usable_pct"] == 64.8


def test_week_on_week_comparison(client):
    d = doctor(client)
    now = utcnow()
    first = reporting.agent_report(d, now)
    assert first["headline"] is None and first["kpis"] == [] and first["compare"] is None

    reporting.record(d.id, "t1", *scan_report(_scan_kpis(68.0, 47.0)), at=now - timedelta(days=8))
    one = reporting.agent_report(d, now)
    assert one["compare"] is None
    assert one["highlights"] == [{"text": "First report: changes show from the next run.",
                                  "good": None}]
    assert [k["key"] for k in one["kpis"]][:8] == [
        "overall", "uniqueness", "completeness", "normalization", "accuracy",
        "contactability", "recency", "engagement"]  # the seven dimensions, in order

    reporting.record(d.id, "t2", *scan_report(_scan_kpis(71.0, 52.0, unreachable=240, dups=5)),
                     at=now - timedelta(hours=1))
    two = reporting.agent_report(d, now)
    assert two["compare"] == "since last week"
    assert two["headline"]["text"].startswith("Scanned 738 leads: health 71/100")
    by = {k["key"]: k for k in two["kpis"]}
    assert by["contactability"] | {"series": None} == by["contactability"] | {
        "value": 52.0, "previous": 47.0, "delta": 5.0, "trend": "up", "good": True,
        "change": "5 pts", "series": None}
    assert by["unreachable_email"]["trend"] == "down" and by["unreachable_email"]["good"]
    assert by["duplicates"]["good"] is False  # more duplicates is worse
    assert by["leads_scanned"]["trend"] == "flat"
    assert {"text": "Contactability up 5 pts since last week: 47 → 52", "good": True} \
        in two["highlights"]
    assert {"text": "Duplicate records up 2 since last week: 3 → 5", "good": False} \
        in two["highlights"]  # bad news is reported too
    assert len(by["overall"]["series"]) == 2


def test_compares_with_the_previous_run_until_a_week_exists(client):
    d = doctor(client)
    now = utcnow()
    reporting.record(d.id, "t1", *scan_report(_scan_kpis(68.0, 47.0)), at=now - timedelta(days=2))
    reporting.record(d.id, "t2", *scan_report(_scan_kpis(68.0, 47.0)), at=now)
    r = reporting.agent_report(d, now)
    assert r["compare"] == f"since the previous run on {(now - timedelta(days=2)):%-d %b}"
    assert r["highlights"] == [{"text": f"No change in any KPI {r['compare']}.", "good": None}]


def test_every_agent_reports_a_headline_and_activity(client, script):
    from app.llm.router import Completion

    turns, _ = script
    agent = make_agent(client, name="Reader", tools=["activity_summary"])
    turns += [Completion("**Quiet week.** 12 visits, no form fills.", 10, 5, 0.01)]
    task_id = client.post("/api/tasks", json={"title": "Summarise",
                                              "agent_id": agent["id"]}).json()["id"]
    assert wait_for(client, task_id, {"done", "failed"})["status"] == "done"
    r = client.get(f"/api/agents/{agent['id']}/report").json()
    assert r["headline"]["text"] == "Quiet week. 12 visits, no form fills."
    assert r["activity"]["tasks_done"] == 1 and r["activity"]["previous"]["tasks_done"] == 0
    assert client.get("/api/agents/nobody/report").status_code == 404
