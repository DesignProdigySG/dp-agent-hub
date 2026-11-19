"""Data health scan: the dimension rules, a full scan on demo Marketo, resuming after a
failure without double counting, restart recovery, and the paid verification skills."""

import asyncio
import json
from collections import Counter
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlmodel import select

from app.workflows.data_health import rules, verify
from app.workflows.data_health.config import ACTIVITY_TYPES, ScanConfig
from tests.conftest import make_agent, wait_for

NOW = datetime(2026, 11, 5, tzinfo=UTC)


def ctx(**kw):
    cfg = ScanConfig()
    return rules.Context(now=NOW, relevant_fields=cfg.relevant_fields, engagement_months=18,
                         **kw)


def lead(**kw):
    return {"id": 1, "firstName": "Marcus", "lastName": "Vance",
            "email": "marcus.vance@northwind.co.uk", "company": "Northwind Offshore",
            "title": "Director of Aviation Operations", "industry": "Oil & Energy",
            "numberOfEmployees": 4200, "country": "United Kingdom",
            "phone": "+44 20 7946 0958", "createdAt": "2026-01-10T00:00:00Z", **kw}


# --- rules ------------------------------------------------------------------------------------


def test_completeness_counts_alternatives_and_suggests_fills():
    score, issues = rules.score_completeness(lead(), ctx())
    assert score == 100 and issues == []
    score, issues = rules.score_completeness(
        lead(country="", numberOfEmployees=None, annualRevenue=900000, phone="",
             mobilePhone=""), ctx())
    assert score == round(100 * 7 / 9)  # employees|revenue counts once; phone|mobile missing
    country = next(i for i in issues if i["field"] == "country")
    assert country["code"] == "fillable" and country["fix"] == "United Kingdom"  # from .uk


def test_normalization_maps_variants_and_casing():
    score, issues = rules.score_normalization(
        lead(country="USA", firstName="MARCUS", email="Marcus.Vance@Northwind.co.uk",
             phone="020 7946 0958"), ctx())
    fixes = {i["field"]: i.get("fix") for i in issues}
    assert fixes["country"] == "United States"
    assert fixes["firstName"] == "Marcus"
    assert fixes["email"] == "marcus.vance@northwind.co.uk"
    assert "phone" in fixes  # not in +international form
    assert score < 100
    # a mapping learned earlier (e.g. by the model) is applied
    _, issues = rules.score_normalization(lead(country="Blighty"),
                                          ctx(countries={"blighty": "United Kingdom"}))
    assert issues[0]["fix"] == "United Kingdom"


def test_accuracy_catches_placeholders_fakes_and_impossible_phones():
    assert rules.score_accuracy(lead(), ctx())[0] == 100
    score, issues = rules.score_accuracy(
        lead(firstName="Test", lastName="Test", email="test@test.example", company="asdf",
             phone="+1-555-1234"), ctx())
    codes = {i["code"] for i in issues}
    assert {"bad_email", "fake_name", "bad_phone", "junk_company"} <= codes
    assert score < 50
    # a suspect name only counts as fake once the AI review confirms it
    odd = lead(firstName="Q", lastName="Zhang")
    assert rules.name_suspicion(odd) == "suspect"
    assert rules.score_accuracy(odd, ctx())[0] == 100
    confirmed = ctx(fake_names={rules.name_check_key(odd): True})
    assert rules.score_accuracy(odd, confirmed)[0] < 100
    # a domain that doesn't resolve
    assert rules.email_problem(lead(), ctx(domains={"northwind.co.uk": False}))


def test_contactability_channels():
    score, issues, flags = rules.score_contactability(lead(), ctx())
    assert score == 100 and flags["email_ok"] and flags["phone_ok"]
    score, issues, flags = rules.score_contactability(lead(unsubscribed=True), ctx())
    assert not flags["email_ok"] and score == 25
    assert issues[0]["code"] == "unreachable_email"
    score, _, flags = rules.score_contactability(lead(email="marcus@gmail.com"), ctx())
    assert flags["free_only"] and score == 85
    # hard bounce from the activity history, and a failed paid verification
    assert not rules.score_contactability(
        lead(), ctx(activity={1: {"hard_bounces": 1}}))[2]["email_ok"]
    assert not rules.score_contactability(
        lead(), ctx(emails={"marcus.vance@northwind.co.uk": {"status": "invalid",
                                                              "usable": False}}))[2]["email_ok"]


def test_recency_and_engagement():
    recent = ctx(activity={1: {"last_activity_at": NOW - timedelta(days=20),
                               "last_engaged_at": NOW - timedelta(days=20), "opens": 4,
                               "clicks": 2, "forms": 1}})
    assert rules.score_recency(lead(), recent)[0] == 100
    score, level, _ = rules.score_engagement(lead(), recent)
    assert level == "hot" and score >= 60
    old = lead(createdAt="2019-03-01T00:00:00Z")
    score, issues = rules.score_recency(old, ctx())
    assert score == 0 and issues[0]["code"] == "stale" and "2019" in issues[0]["message"]
    assert rules.score_engagement(old, ctx())[1] == "dormant"


def test_duplicates_group_by_email_name_phone_and_name_company():
    leads = [
        lead(id=1, email="m.vance@northwind.co.uk"),
        lead(id=2, email="M.VANCE@northwind.co.uk", title="", phone=""),  # same email
        lead(id=3, email="marcus@other.com", company="Northwind Offshore Ltd"),  # name+company
        lead(id=4, firstName="Sarah", lastName="Jenkins", email="s@fabrikam.com",
             company="Fabrikam"),
        lead(id=5, firstName="Test", lastName="Test", email="a@x.com", company="Northwind"),
        lead(id=6, firstName="Test", lastName="Test", email="b@x.com", company="Northwind"),
    ]
    completeness = {x["id"]: rules.score_completeness(x, ctx())[0] for x in leads}
    groups = rules.duplicate_groups(leads, completeness)
    assert set(groups) == {1, 2, 3}  # placeholders aren't grouped as one person
    assert len({g[0] for g in groups.values()}) == 1
    survivor = {g[3] for g in groups.values()}
    assert survivor in ({1}, {3})  # the most complete record wins, never the sparse one
    sizes = Counter(g[0] for g in groups.values())
    assert rules.score_uniqueness(2, groups, sizes)[0] == 0
    assert rules.score_uniqueness(4, groups, sizes) == (100, [])


# --- a full scan ----------------------------------------------------------------------------


@pytest.fixture
def doctor(client):
    """The user's Data Doctor (an ordinary agent) with the data health add-on installed."""
    from app import presets

    make_agent(client, id="data_doctor", name="Data Doctor", tools=["rest_get_leads"],
               home_zone="database")
    agent_id, outcome = asyncio.run(presets.install("data_health_scan"))
    assert (agent_id, outcome) == ("data_doctor", "added")
    client.app.state.hub.sync_roster()
    return client.app.state.hub.deps.marketo


def scan_task(client, **params):
    agent = next(a for a in client.get("/api/agents").json() if a["id"] == "data_doctor")
    template = next(t for t in agent["templates"] if t["title"] == "Full data health scan")
    r = client.post("/api/tasks", json={"title": template["title"], "agent_id": "data_doctor",
                                        "params": {**template["params"], "pace_s": 0,
                                                   **params}})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_addon_keeps_the_agent_and_adds_skills_and_template(client, doctor):
    from app import presets

    d = client.get("/api/agents").json()
    doc = next(a for a in d if a["id"] == "data_doctor")
    assert doc["tools"] == ["rest_get_leads"] and doc["name"] == "Data Doctor"
    assert [t["title"] for t in doc["templates"]] == ["Full data health scan"]
    skills = {s["name"] for s in client.get("/api/skills").json()}
    assert {verify.EMAIL_SKILL, verify.PHONE_SKILL, "Data health check (7 dimensions)"} <= skills
    asyncio.run(presets.install("data_health_scan"))  # twice: nothing duplicated
    from app.agents import registry

    d = registry.get("data_doctor")
    assert len(d.templates) == 1 and len(d.skill_ids) == 3


def test_full_scan_on_demo_data(client, doctor):
    from app.db import HealthScan, KpiSnapshot, LeadHealth, session

    task = wait_for(client, scan_task(client), {"done", "failed"}, timeout=60)
    assert task["status"] == "done", task["result"]
    assert "leads scanned" in task["result"] and "### Duplicates" in task["result"]
    with session() as s:
        scan = s.exec(select(HealthScan)).one()
        rows = list(s.exec(select(LeadHealth).where(LeadHealth.scan_id == scan.id)))
        snap = {k.metric: k.value_num for k in s.exec(
            select(KpiSnapshot).where(KpiSnapshot.scope == "data_health"))}
    k = scan.kpis
    assert scan.status == "done" and k["total"] == len(doctor.leads) == len(rows)
    # database-wide numbers are exact counts over every lead
    assert k["dimensions"]["overall"]["avg"] == round(sum(r.overall for r in rows) / len(rows), 1)
    assert k["duplicates"]["redundant"] == sum(r.dup_role == "duplicate" for r in rows) >= 18
    assert k["contactability"]["usable"] == sum(bool(r.reach) for r in rows)
    unsub = sum(bool(x["unsubscribed"]) for x in doctor.leads.values())
    assert k["contactability"]["unreachable_email"] >= unsub
    assert sum(k["engagement_levels"].values()) == len(rows)
    assert snap["leads"] == len(rows) and "overall_avg" in snap
    assert k["notes"]["dns"] == "skipped (demo data)"
    assert k["notes"]["email_verification"] == "skill attached, but no ZeroBounce key in Settings"
    # drill-down API
    worst = client.get(f"/api/data-health/scans/{scan.id}/leads?sort=accuracy&limit=5").json()
    assert worst["total"] == len(rows) and len(worst["rows"]) == 5
    assert worst["rows"][0]["scores"]["accuracy"] <= worst["rows"][-1]["scores"]["accuracy"]
    dups = client.get(f"/api/data-health/scans/{scan.id}/duplicates").json()
    assert dups["total"] == k["duplicates"]["groups"]
    assert dups["groups"][0]["members"][0]["role"] == "survivor"
    log = client.get(f"/api/tasks/{task['id']}/log").json()
    assert log[0]["data"] == {"kind": "health_scan", "scan_id": scan.id, "resumed": False}
    # the agent's KPIs show the scan
    status = client.app.state.hub.statuses["data_doctor"]
    assert status.metrics["leads_scanned"] == len(rows)


def test_scan_resumes_where_it_stopped_without_double_counting(client, doctor, monkeypatch):
    from app.db import HealthScan, LeadActivityAgg, session
    from app.workflows.data_health import scan as scan_mod

    real = type(doctor).activity_export_rows
    calls = {"n": 0}

    async def flaky(self, export_id):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("Marketo went away")
        return await real(self, export_id)

    monkeypatch.setattr(type(doctor), "activity_export_rows", flaky)
    first = wait_for(client, scan_task(client), {"done", "failed"}, timeout=60)
    assert first["status"] == "failed"
    assert "activities phase; run the task again" in first["result"]
    with session() as s:
        scan = s.exec(select(HealthScan)).one()
    assert scan.status == "failed" and scan.cursor["leads"]["done"]
    assert scan.cursor["activities"]["i"] == 2  # windows 1-2 saved, 3 failed

    second = wait_for(client, scan_task(client), {"done", "failed"}, timeout=60)
    assert second["status"] == "done", second["result"]
    assert "Continued an earlier scan" in second["result"]
    with session() as s:
        scans = list(s.exec(select(HealthScan)))
        agg = list(s.exec(select(LeadActivityAgg).where(LeadActivityAgg.scan_id == scan.id)))
    assert len(scans) == 1 and scans[0].counts["resumed"] == 1
    # every window counted exactly once: re-derive the totals from the demo exports (off the
    # app's event loop, so skip its rate governor)
    async def no_tick(channel):
        return None

    monkeypatch.setattr(doctor, "_tick", no_tick)
    expected = Counter()
    for w0, w1 in scans[0].cursor["activities"]["windows"]:
        export_id = asyncio.run(doctor.activity_export_start(
            datetime.fromisoformat(w0), datetime.fromisoformat(w1), ACTIVITY_TYPES))
        for a in scan_mod._aggregate(asyncio.run(real(doctor, export_id))).values():
            for c in ("opens", "clicks", "forms", "visits"):
                expected[c] += a.get(c, 0)
    got = Counter()
    for a in agg:
        for c in ("opens", "clicks", "forms", "visits"):
            got[c] += getattr(a, c)
    assert got == expected


def test_restart_requeues_an_interrupted_scan(client, doctor):
    from app.db import Task, session
    from app.events.schema import TaskStatus

    hub = client.app.state.hub
    with session() as s:
        t = Task(title="scan", agent_id="data_doctor", status=TaskStatus.IN_PROGRESS,
                 params={"workflow": "data_health_scan"})
        other = Task(title="chat", agent_id="data_doctor", status=TaskStatus.IN_PROGRESS)
        s.add(t)
        s.add(other)
        s.commit()
        ids = t.id, other.id
    hub.recover()
    with session() as s:
        assert s.get(Task, ids[0]).status == TaskStatus.QUEUED
        assert s.get(Task, ids[1]).status == TaskStatus.FAILED


def test_task_cannot_pick_a_workflow_its_agent_does_not_offer(client, doctor):
    from app.agents import registry
    from app.db import Task
    from app.hub import workflow_for

    d = registry.get("data_doctor")
    assert workflow_for(Task(title="x", agent_id="data_doctor",
                             params={"workflow": "data_health_scan"}), d) == "data_health_scan"
    assert workflow_for(Task(title="x", agent_id="data_doctor",
                             params={"workflow": "some_other_workflow"}), d) == ""
    assert workflow_for(Task(title="x", agent_id="data_doctor"), d) == ""


# --- paid verification ------------------------------------------------------------------------


def test_zerobounce_batches_and_caches(db):
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        sent.append([e["email_address"] for e in body["email_batch"]])
        assert body["api_key"] == "zb-key" and "zb-key" not in str(request.url)
        return httpx.Response(200, json={"email_batch": [
            {"address": e, "status": "valid" if e.startswith("ok") else "invalid"}
            for e in sent[-1]]})

    async def run(emails):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await verify.zerobounce(emails, "zb-key", http=http)

    emails = [f"ok{i}@acme.com" for i in range(150)] + ["bad@acme.com"]
    out = asyncio.run(run(emails))
    assert [len(b) for b in sent] == [100, 51]
    assert out["ok1@acme.com"]["usable"] and not out["bad@acme.com"]["usable"]
    assert asyncio.run(run(emails)) == {} and len(sent) == 2  # all cached: nothing sent
    assert verify.cached("email", ["bad@acme.com"])["bad@acme.com"]["status"] == "invalid"


def test_twilio_errors_do_not_leak_credentials(db):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("+14155550100"):
            return httpx.Response(200, json={"valid": True, "country_code": "US"})
        return httpx.Response(401, json={"message": "bad auth"})

    async def run(numbers):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                     auth=("AC123", "secret-token")) as http:
            return await verify.twilio(numbers, "AC123", "secret-token", http=http)

    assert asyncio.run(run(["+14155550100"]))["+14155550100"]["usable"]
    with pytest.raises(verify.VerificationError) as e:
        asyncio.run(run(["+14155550199"]))
    assert "secret-token" not in str(e.value) and "401" in str(e.value)


def test_verification_runs_only_with_the_skill_and_a_key(client, doctor, monkeypatch):
    from app.db import HealthScan, session

    calls = []

    async def fake_zb(emails, key, http=None):
        calls.append(len(emails))
        return {e: {"status": "invalid", "usable": False} for e in emails[:3]}

    monkeypatch.setattr(verify, "zerobounce", fake_zb)
    # through the API, so the change (and anything it rebuilds) happens on the app's loop
    r = client.put("/api/config", json={"changes": {"zerobounce_api_key": "zb",
                                                    "verify_max_per_scan": 10}})
    assert r.status_code == 200, r.text
    task = wait_for(client, scan_task(client), {"done", "failed"}, timeout=60)
    assert task["status"] == "done", task["result"]
    with session() as s:
        scan = s.exec(select(HealthScan)).one()
    assert calls == [10]  # capped per scan
    assert scan.counts["email_verification"] == "3 checked, 3 not deliverable; " \
        f"{scan.counts['email_verification'].split('; ')[1]}"
    assert scan.counts["phone_verification"] == \
        "skill attached, but no Twilio credentials in Settings"


def test_mail_domain_check_uses_mx_then_address_records(monkeypatch):
    """A domain can take email if it has MX records, or no MX but an address record; only a
    domain with neither (or that doesn't exist) counts against the lead; a timeout is unknown."""
    import dns.exception
    import dns.resolver

    from app.workflows.data_health import scan as scan_mod

    zones = {("mx.example", "MX"): "ok", ("aonly.example", "A"): "ok",
             ("gone.example", "*"): "nx", ("slow.example", "*"): "timeout"}

    class FakeResolver:
        lifetime = 0

        async def resolve(self, name, rtype):
            how = zones.get((name, rtype)) or zones.get((name, "*"))
            if how == "ok":
                return ["record"]
            if how == "nx":
                raise dns.resolver.NXDOMAIN()
            if how == "timeout":
                raise dns.exception.Timeout()
            raise dns.resolver.NoAnswer()

    monkeypatch.setattr(scan_mod.dns.asyncresolver, "Resolver", FakeResolver)
    found = asyncio.run(scan_mod._check_domains(
        ["mx.example", "aonly.example", "gone.example", "slow.example", "nomail.example"]))
    assert found == {"mx.example": True, "aonly.example": True, "gone.example": False,
                     "nomail.example": False}  # slow.example: unknown, not recorded
