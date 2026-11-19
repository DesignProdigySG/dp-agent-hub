"""The single surface agents use to reach Marketo.

`LiveMarketo` routes lead/bulk work to the REST client and asset/orchestration work to the
MCP server. `DemoMarketo` serves an in-memory sandbox so the whole hub runs offline.
"""

import base64
import random
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from app.marketo.governor import RateGovernor
from app.marketo.mcp_client import MarketoMcpClient
from app.marketo.rest_client import MarketoRestClient

LEAD_FIELDS = [
    "id", "email", "firstName", "lastName", "company", "title", "country", "industry",
    "numberOfEmployees", "unsubscribed", "phone",
]


class MarketoGateway(Protocol):
    # REST / Bulk channel
    async def export_leads(self, fields: list[str], days: int = 30) -> list[dict]: ...
    async def get_leads(
        self, filter_type: str, values: list[str], fields: list[str]
    ) -> list[dict]: ...
    async def update_leads(self, leads: list[dict]) -> list[dict]: ...
    async def merge_leads(self, winner_id: int, loser_ids: list[int]) -> None: ...
    async def add_leads_to_list(self, list_id: int, lead_ids: list[int]) -> list[dict]: ...
    async def get_lead_activities(
        self, activity_type_ids: list[int], since: datetime
    ) -> list[dict]: ...
    # MCP channel
    async def list_leads(self, list_id: int, batch_size: int, fields: list[str]) -> list[dict]: ...
    async def list_membership(self, list_id: int, lead_ids: list[int]) -> dict[int, bool]: ...
    async def remove_leads_from_list(self, list_id: int, lead_ids: list[int]) -> list[dict]: ...
    async def request_campaign(
        self, campaign_id: int, lead_ids: list[int], tokens: list[dict[str, str]] | None = None
    ) -> list[dict]: ...
    # Asset API (app/marketo/asset_api.py)
    async def asset(self, call: dict[str, Any]) -> Any: ...
    # Data health scan
    async def lead_field_names(self) -> list[str]: ...
    async def activity_export_start(
        self, start: datetime, end: datetime, type_ids: list[int]
    ) -> str: ...
    async def activity_export_rows(self, export_id: str) -> list[dict]: ...
    async def mcp(self, tool: str, args: dict[str, Any]) -> Any: ...
    async def mcp_tools(self) -> list[dict[str, Any]]: ...  # [{name, description, parameters}]
    async def aclose(self) -> None: ...


class LiveMarketo:
    def __init__(self, rest: MarketoRestClient, mcp_client: MarketoMcpClient | None):
        self.rest = rest
        self._mcp = mcp_client

    async def export_leads(self, fields, days=30):
        return await self.rest.bulk_export_leads(fields, days)

    async def get_leads(self, filter_type, values, fields):
        return await self.rest.get_leads(filter_type, values, fields)

    async def update_leads(self, leads):
        return await self.rest.update_leads(leads)

    async def merge_leads(self, winner_id, loser_ids):
        await self.rest.merge_leads(winner_id, loser_ids)

    async def add_leads_to_list(self, list_id, lead_ids):
        return await self.rest.add_leads_to_list(list_id, lead_ids)

    async def get_lead_activities(self, activity_type_ids, since):
        return await self.rest.get_lead_activities(activity_type_ids, since)

    async def list_leads(self, list_id, batch_size, fields):
        return await self.rest.list_leads(list_id, batch_size, fields)

    async def list_membership(self, list_id, lead_ids):
        return await self.rest.list_membership(list_id, lead_ids)

    async def remove_leads_from_list(self, list_id, lead_ids):
        return await self.rest.remove_leads_from_list(list_id, lead_ids)

    async def request_campaign(self, campaign_id, lead_ids, tokens=None):
        return await self.rest.request_campaign(campaign_id, lead_ids, tokens)

    async def lead_field_names(self):
        return await self.rest.lead_field_names()

    async def asset(self, call):
        return await self.rest.asset_call(call)

    async def activity_export_start(self, start, end, type_ids):
        return await self.rest.activity_export_start(start, end, type_ids)

    async def activity_export_rows(self, export_id):
        return await self.rest.bulk_rows("activities", export_id)

    async def mcp(self, tool, args):
        if self._mcp is None:
            raise RuntimeError("MARKETO_MCP_URL is empty; the Marketo MCP channel is disabled")
        return await self._mcp.call(tool, args)

    async def mcp_tools(self):
        if self._mcp is None:
            return []
        return [{"name": t.name, "description": t.description or "",
                 "parameters": t.args_schema if isinstance(t.args_schema, dict)
                 else t.args_schema.model_json_schema() if t.args_schema else {}}
                for t in (await self._mcp.tools()).values()]

    async def aclose(self):
        await self.rest.aclose()


# --- Demo sandbox ------------------------------------------------------------------------

_FIRST = ["ana", "Ben", "CHLOE", "dev", "Elena", "Farid", "Grace", "hiro", "Isla", "Jon",
          "Kai", "Lena", "Mateo", "Nia", "Omar", "Priya", "Quinn", "Rosa", "Sam", "Tara"]
_LAST = ["Ng", "Okafor", "smith", "Rossi", "Kim", "Patel", "garcia", "Muller", "Silva", "Cohen"]
_COMPANIES = [("Acme Robotics", "Manufacturing", 1200), ("Northwind", "Retail", 340),
              ("Globex", "Software", 5400), ("Initech", "Software", 220),
              ("Umbrella Health", "Healthcare", 8800), ("Stark Freight", "Logistics", 950),
              ("Vandelay Imports", "Retail", 45), ("Hooli", "Software", 15000)]
_TITLES = ["VP Marketing", "Marketing Ops Manager", "cmo", "Developer", "Director of Demand Gen",
           "Intern", "Head of Growth", "Sales Rep", "Marketing Coordinator", "CTO"]
_COUNTRIES = ["United States", "USA", "U.S.", "Germany", "DE", "United Kingdom", "UK", "France",
              "", "Canada"]


def _demo_leads(n: int = 240, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    leads = []
    for i in range(1, n + 1):
        first, last = rng.choice(_FIRST), rng.choice(_LAST)
        company, industry, size = rng.choice(_COMPANIES)
        domain = company.split()[0].lower() + ".com"
        email = f"{first.lower()}.{last.lower()}@{domain}"
        if rng.random() < 0.08:
            email = email.upper()
        if rng.random() < 0.05:
            email = email.replace("@", "")  # invalid
        leads.append({
            "id": i,
            "email": email,
            "firstName": first,
            "lastName": last,
            "company": company,
            "title": rng.choice(_TITLES) if rng.random() > 0.1 else "",
            "country": rng.choice(_COUNTRIES),
            "industry": industry if rng.random() > 0.15 else "",
            "numberOfEmployees": size,
            "unsubscribed": rng.random() < 0.07,
            "phone": f"+1-555-{rng.randint(1000, 9999)}" if rng.random() > 0.3 else "",
        })
    # deliberate duplicates (same person, different casing / later record)
    for j in rng.sample(range(n), 18):
        dup = dict(leads[j], id=len(leads) + 1)
        dup["email"] = dup["email"].upper() if rng.random() < 0.5 else dup["email"]
        dup["phone"] = ""
        leads.append(dup)
    dates = random.Random(seed + 1)  # separate stream: the fields above stay as they were
    for lead in leads:
        created = datetime(2019, 1, 1, tzinfo=UTC) + timedelta(days=dates.randint(0, 2500))
        lead["createdAt"] = created.isoformat().replace("+00:00", "Z")
        lead["updatedAt"] = (created + timedelta(days=dates.randint(0, 300))).isoformat() \
            .replace("+00:00", "Z")
    return leads


_FORM_DEFAULT_FIELDS = ("FirstName", "LastName", "Email")


# A static list for demos: ~30 attendees, a few with bad emails or gaps, three strong fits.
WEBINAR_LIST = 1003
WEBINAR_LIST_NAME = "Q4 Webinar Attendees"
_STRONG_FITS = [
    {"id": 301, "email": "marcus.vance@umbrellahealth.com", "firstName": "Marcus",
     "lastName": "Vance", "company": "Umbrella Health", "title": "VP Operations",
     "country": "United States", "industry": "Healthcare", "numberOfEmployees": 8800,
     "unsubscribed": False, "phone": "+1-555-0142"},
    {"id": 302, "email": "sarah.jenkins@hooli.com", "firstName": "Sarah", "lastName": "Jenkins",
     "company": "Hooli", "title": "Chief Operating Officer", "country": "United States",
     "industry": "Software", "numberOfEmployees": 15000, "unsubscribed": False,
     "phone": "+1-555-0177"},
    {"id": 303, "email": "lena.rossi@starkfreight.com", "firstName": "Lena", "lastName": "Rossi",
     "company": "Stark Freight", "title": "Head of Fleet", "country": "Germany",
     "industry": "Logistics", "numberOfEmployees": 950, "unsubscribed": False,
     "phone": "+49-30-555-0199"},
]


def _webinar_members(leads: dict[int, dict]) -> set[int]:
    good = [i for i, x in leads.items() if "@" in x["email"] and not x["unsubscribed"]
            and x["title"] and i <= 240]
    weak = [i for i, x in leads.items() if ("@" not in x["email"] or not x["title"]
                                             or not x["industry"]) and i <= 240]
    return set(good[:22]) | set(weak[:5]) | {x["id"] for x in _STRONG_FITS}


class DemoMarketo:
    """In-memory stand-in that mirrors the shapes of the real REST + MCP responses."""

    def __init__(self, governor: RateGovernor):
        self._gov = governor
        self.leads = {lead["id"]: lead for lead in _demo_leads()}
        for lead in _STRONG_FITS:
            self.leads[lead["id"]] = {**lead, "createdAt": "2026-10-20T09:00:00Z",
                                      "updatedAt": "2026-11-02T09:00:00Z"}
        self.lists: dict[int, set[int]] = {1001: set(), 1002: set(),
                                           WEBINAR_LIST: _webinar_members(self.leads)}
        self.programs = {
            2001: {"id": 2001, "name": "TEMPLATE - Webinar", "type": "Event", "channel": "Webinar"},
            2002: {"id": 2002, "name": "TEMPLATE - Nurture", "type": "Engagement",
                   "channel": "Nurture"},
        }
        self.campaigns = {
            3001: {"id": 3001, "name": "01 - Registration", "programId": 2001, "isActive": False},
            3002: {"id": 3002, "name": "02 - Attended", "programId": 2001, "isActive": False},
        }
        self.snippets = {
            4001: {"id": 4001, "name": "Footer - Legal", "status": "approved", "type": "HTML",
                   "content": '<p>© Acme · <a href="https://acme.example/privacy">Privacy</a> · '
                              '<a href="{{system.unsubscribeLink}}">Unsubscribe</a></p>'},
            4002: {"id": 4002, "name": "Hero - Q4 Launch", "status": "draft", "type": "HTML",
                   "content": '<h1>Hi {{lead.First Name:default=there}}</h1><a href="">Learn more'
                              '</a><img src="hero.png">'},
            4003: {"id": 4003, "name": "Signature - Sales", "status": "approved", "type": "HTML",
                   "content": "<p>Talk soon,<br>{{my.Sender Name}}</p>"},
        }
        self.forms: dict[int, dict[str, Any]] = {}
        self.assets: dict[int, dict[str, Any]] = {}  # Asset API stand-in
        self.asset_calls: list[dict[str, Any]] = []
        self._next_id = 5000
        self.campaign_requests: list[dict[str, Any]] = []  # request_campaign calls, in order

    async def _tick(self, channel: str) -> None:
        await self._gov.run(channel, _noop)

    def _id(self) -> int:
        self._next_id += 1
        return self._next_id

    async def export_leads(self, fields, days=30):
        for _ in range(3):  # create / enqueue / file
            await self._tick("rest")
        return [{f: lead.get(f) for f in fields} for lead in self.leads.values()]

    async def get_leads(self, filter_type, values, fields):
        await self._tick("rest")
        vals = {str(v).lower() for v in values}
        return [{f: lead.get(f) for f in fields} for lead in self.leads.values()
                if str(lead.get(filter_type, "")).lower() in vals]

    async def update_leads(self, leads):
        out = []
        for i in range(0, len(leads), 300):
            await self._tick("rest")
            for change in leads[i:i + 300]:
                self.leads[change["id"]].update(change)
                out.append({"id": change["id"], "status": "updated"})
        return out

    async def merge_leads(self, winner_id, loser_ids):
        await self._tick("rest")
        for lid in loser_ids:
            self.leads.pop(lid, None)

    async def add_leads_to_list(self, list_id, lead_ids):
        await self._tick("rest")
        self.lists.setdefault(list_id, set()).update(lead_ids)
        return [{"id": lid, "status": "added"} for lid in lead_ids]

    async def list_leads(self, list_id, batch_size, fields):
        await self._tick("rest")
        members = sorted(self.lists.get(list_id, set()))[:batch_size]
        return [{f: self.leads[i].get(f) for f in fields if f in self.leads[i] or f == "id"}
                for i in members if i in self.leads]

    async def list_membership(self, list_id, lead_ids):
        await self._tick("rest")
        return {lid: lid in self.lists.get(list_id, set()) for lid in lead_ids}

    async def remove_leads_from_list(self, list_id, lead_ids):
        await self._tick("rest")
        self.lists.get(list_id, set()).difference_update(lead_ids)
        return [{"id": lid, "status": "removed"} for lid in lead_ids]

    async def request_campaign(self, campaign_id, lead_ids, tokens=None):
        await self._tick("rest")
        self.campaign_requests.append({"campaign_id": campaign_id, "lead_ids": list(lead_ids),
                                       "tokens": {t["name"]: t["value"] for t in tokens or []}})
        return [{"id": campaign_id}]

    def _mcp_get_leads_by_filter(self, filterType, filterValues, fields=None, **_):
        values = {str(v).strip().lower() for v in filterValues}
        wanted = list(fields or [])
        rows = [lead for lead in self.leads.values()
                if str(lead.get(filterType, "")).lower() in values]
        return [{f: r.get(f) for f in wanted} if wanted else r for r in rows]  # as the live server

    async def get_lead_activities(self, activity_type_ids, since):
        await self._tick("rest")
        rng = random.Random(len(self.leads))
        kinds = {1: "Visit Webpage", 2: "Fill Out Form", 7: "Email Delivered", 10: "Open Email",
                 11: "Click Email"}
        ids = list(self.leads)
        return [{"leadId": rng.choice(ids), "activityTypeId": t, "activityType": kinds.get(t, t),
                 "primaryAttributeValue": rng.choice(["/pricing", "/blog/ai-ops", "Q4 Webinar",
                                                      "/integrations/marketo", "Newsletter"])}
                for t in activity_type_ids for _ in range(rng.randint(15, 60))]

    async def lead_field_names(self):
        await self._tick("rest")
        return sorted({k for lead in self.leads.values() for k in lead})

    async def asset(self, call):
        """Asset API stand-in: records each call; creates return a new id, reads return the
        assets created so far under that path. Emails get their template's editable sections,
        which can be read and filled in (plain or per segment)."""
        await self._tick("rest")
        self.asset_calls.append(call)
        if (special := self._email_sections(call)) is not None:
            return special
        if call["method"] == "GET":
            return {"success": True, "result": [a for a in self.assets.values()
                                                if a["_path"] == call["path"]]}
        aid = self._id()
        body = {k: v for k, v in call["body"].items() if k not in call.get("files", [])}
        self.assets[aid] = {"id": aid, "status": "draft", "_path": call["path"], **body,
                            "_content": call["body"].get("content", "")}
        if call["path"].endswith("/emails.json") and (t := self.assets.get(
                int(call["body"].get("template") or 0))):
            self.assets[aid]["_sections"] = self._sections_of(t.get("_content", ""))
        return {"success": True, "result": [{"id": aid, "status": "draft",
                                             **{k: v for k, v in body.items()
                                                if k in ("name", "folder")}}]}

    SEGMENTATION = {"id": 2001, "name": "Guest Type",
                    "segments": ["VIP Customer", "Partner", "Default"]}

    @staticmethod
    def _sections_of(html: str) -> dict[str, dict[str, Any]]:
        from app.marketo import email_sections

        return {sec.id: {"type": "Text", "value": [{"type": "HTML", "value": sec.inner}]}
                for sec in email_sections.sections(html)}

    def _email_sections(self, call) -> dict[str, Any] | None:
        """Calls on an email's sections, a template's content, and segmentations; None for
        everything else (the generic stand-in handles it)."""
        path, body = call["path"], call["body"]
        if path.endswith("/segmentation.json"):
            seg = self.SEGMENTATION
            return {"success": True, "result": [{"id": seg["id"], "name": seg["name"],
                                                 "status": "approved"}]}
        if m := re.search(r"/segmentation/(\d+)/segments\.json$", path):
            return {"success": True, "result": [
                {"id": 3000 + i, "name": n} for i, n in enumerate(self.SEGMENTATION["segments"])]
                if int(m.group(1)) == self.SEGMENTATION["id"] else []}
        if (m := re.search(r"/emailTemplate/(\d+)/content\.json$", path)) and \
                call["method"] == "POST":
            if t := self.assets.get(int(m.group(1))):
                t["_draft"] = body.get("content", "")
            return {"success": True, "result": [{"id": int(m.group(1))}]}
        if m := re.search(r"/emailTemplate/(\d+)/approveDraft\.json$", path):
            t = self.assets.get(int(m.group(1))) or {}
            if t.get("_draft"):  # the new layout reaches every email built from it
                t["_content"] = t.pop("_draft")
                fresh = self._sections_of(t["_content"])
                for e in self.assets.values():
                    if str(e.get("template")) == str(t.get("id")):
                        kept = {k: v for k, v in e.get("_sections", {}).items() if k in fresh}
                        e["_sections"] = {**fresh, **kept}
            return {"success": True, "result": [{"id": t.get("id")}]}
        m = re.search(r"/email/(\d+)/(content(?:/([\w-]+))?|dynamicContent/([^/]+))\.json$",
                      path)
        if not m or (m.group(2) == "content" and call["method"] == "POST"):
            return None  # headers (subject, sender): the generic stand-in
        email = self.assets.get(int(m.group(1)))
        if email is None:
            return {"success": False, "errors": [{"code": "702", "message": "No such email"}]}
        sections = email.setdefault("_sections", {})
        if m.group(2) == "content":
            return {"success": True, "result": [
                {"htmlId": k, "contentType": v["type"], "value": v["value"]}
                for k, v in sections.items()]}
        if html_id := m.group(3):
            if html_id not in sections:
                return {"success": False, "errors": [{"code": "702",
                                                      "message": f"No section {html_id}"}]}
            if body.get("type") == "DynamicContent":
                cid = base64.b64encode(f"ES-{html_id}".encode()).decode()
                sections[html_id] = {"type": "DynamicContent", "value": cid,
                                     "segmentation": int(body["value"]), "segments": {}}
            else:
                sections[html_id] = {"type": "Text",
                                     "value": [{"type": "HTML", "value": body.get("value", "")}]}
            return {"success": True, "result": [{"id": email["id"]}]}
        sec = next((v for v in sections.values() if v.get("value") == m.group(4)), None)
        if sec is None:
            return {"success": False, "errors": [{"code": "702", "message": "No such content"}]}
        if call["method"] == "POST":
            sec["segments"][body.get("segment")] = body.get("value", "")
        return {"success": True, "result": [{
            "id": email["id"], "segmentation": sec["segmentation"],
            "content": [{"segmentName": k, "type": "HTML", "content": v}
                        for k, v in sec["segments"].items()]}]}

    async def activity_export_start(self, start, end, type_ids):
        await self._tick("rest")
        return f"demo|{start.isoformat()}|{end.isoformat()}|{','.join(map(str, type_ids))}"

    async def activity_export_rows(self, export_id):
        """Deterministic activity for each window: most demo leads engage now and then."""
        await self._tick("rest")
        _, start, end, types = export_id.split("|")
        t0, t1 = datetime.fromisoformat(start), datetime.fromisoformat(end)
        type_ids = [int(t) for t in types.split(",") if t]
        rng = random.Random(start)
        span = max(1, int((t1 - t0).total_seconds()))
        rows = []
        for lead_id in sorted(self.leads):
            if lead_id % 4 == 0 or rng.random() < 0.5:  # a quarter never engage
                continue
            for _ in range(rng.randint(1, 4)):
                at = t0 + timedelta(seconds=rng.randrange(span))
                rows.append({"leadId": str(lead_id), "activityTypeId": str(rng.choice(type_ids)),
                             "activityDate": at.isoformat().replace("+00:00", "Z")})
        return rows

    async def mcp(self, tool, args):
        await self._tick("mcp")
        handler = getattr(self, f"_mcp_{tool}", None)
        if handler is None:
            raise KeyError(f"demo MCP has no tool {tool!r}")
        return handler(**args)

    async def mcp_tools(self):
        return DEMO_MCP_TOOLS

    def _mcp_browse_programs(self, maxReturn=20, **_):
        return list(self.programs.values())[:maxReturn]

    def _mcp_clone_program(self, id, name, description=None, folder=None):
        new = dict(self.programs[id], id=self._id(), name=name)
        self.programs[new["id"]] = new
        for c in [c for c in self.campaigns.values() if c["programId"] == id]:
            cid = self._id()
            self.campaigns[cid] = dict(c, id=cid, programId=new["id"], isActive=False)
        return new

    def _mcp_browse_smart_campaigns(self, folder=None, maxReturn=20, **_):
        rows = list(self.campaigns.values())
        if folder:
            rows = [c for c in rows if c["programId"] == folder["id"]]
        return rows[:maxReturn]

    def _mcp_activate_smart_campaign(self, id, confirm=False):
        if not confirm:
            return {"status": "CONFIRMATION_REQUIRED", "id": id}
        self.campaigns[id]["isActive"] = True
        return {"id": id, "isActive": True}

    def _mcp_browse_snippets(self, maxReturn=20, status=None, **_):
        rows = [s for s in self.snippets.values() if status in (None, s["status"])]
        return [{k: v for k, v in s.items() if k != "content"} for s in rows[:maxReturn]]

    def _mcp_get_snippet_content(self, id, status=None):
        s = self.snippets[id]
        return [{"type": s["type"], "content": s["content"]},
                {"type": "Text" if s["type"] == "HTML" else "HTML", "content": ""}]

    def _mcp_create_snippet(self, name, type, folder, description=None):
        sid = self._id()
        self.snippets[sid] = {"id": sid, "name": name, "status": "draft", "type": type,
                              "content": ""}
        return {"id": sid, "name": name, "status": "draft"}

    def _mcp_update_snippet_content(self, id, type, content):
        self.snippets[id].update(type=type, content=content)
        return {"id": id}

    def _mcp_browse_folders(self, root=2, maxReturn=20, **_):
        return [{"id": 1101, "name": "Forms", "folderType": "Form", "type": "Folder"},
                {"id": 1102, "name": "Snippets", "folderType": "Snippet", "type": "Folder"}]

    def _mcp_create_form(self, name, folder, description=None, **_):
        fid = self._id()
        self.forms[fid] = {"id": fid, "name": name, "status": "draft", "folder": folder,
                           "fields": list(_FORM_DEFAULT_FIELDS)}
        return {"id": fid, "name": name, "status": "draft"}

    def _mcp_add_field_to_form(self, id, fieldId, label=None, required=False, **_):
        form = self.forms[id]
        if fieldId in form["fields"]:
            raise ValueError(f"field {fieldId} is already on form {id}")
        form["fields"].append(fieldId)
        return {"id": id, "fieldId": fieldId, "label": label, "required": required}

    def _mcp_approve_snippet(self, id):
        self.snippets[id]["status"] = "approved"
        return {"id": id, "status": "approved"}

    async def aclose(self):
        pass


def _obj(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required}


_INT = {"type": "integer"}
_MAX = {"type": "integer", "description": "Max results (default 20)"}
# The subset of Adobe's Marketo MCP tools the demo sandbox implements, with the same names.
DEMO_MCP_TOOLS: list[dict[str, Any]] = [
    {"name": "browse_programs", "description": "List marketing programs.",
     "parameters": _obj({"maxReturn": _MAX}, [])},
    {"name": "clone_program", "description": "Clone a program (and its smart campaigns).",
     "parameters": _obj({"id": _INT, "name": {"type": "string"},
                         "description": {"type": "string"}}, ["id", "name"])},
    {"name": "browse_smart_campaigns",
     "description": "List smart campaigns, optionally inside a program folder.",
     "parameters": _obj({"folder": {"type": "object", "properties": {
         "id": _INT, "type": {"type": "string", "enum": ["Program", "Folder"]}}},
         "maxReturn": _MAX}, [])},
    {"name": "activate_smart_campaign",
     "description": "Activate a trigger smart campaign. Pass confirm=true to apply.",
     "parameters": _obj({"id": _INT, "confirm": {"type": "boolean"}}, ["id"])},
    {"name": "browse_snippets", "description": "List snippets (without content).",
     "parameters": _obj({"maxReturn": _MAX,
                         "status": {"type": "string", "enum": ["draft", "approved"]}}, [])},
    {"name": "get_snippet_content", "description": "Get a snippet's HTML and text content.",
     "parameters": _obj({"id": _INT}, ["id"])},
    {"name": "create_snippet", "description": "Create an empty draft snippet in a folder.",
     "parameters": _obj({"name": {"type": "string"},
                         "type": {"type": "string", "enum": ["HTML", "Text"]},
                         "folder": {"type": "object", "properties": {
                             "id": _INT, "type": {"type": "string"}}},
                         "description": {"type": "string"}}, ["name", "type", "folder"])},
    {"name": "update_snippet_content", "description": "Replace a draft snippet's content.",
     "parameters": _obj({"id": _INT, "type": {"type": "string", "enum": ["HTML", "Text"]},
                         "content": {"type": "string"}}, ["id", "type", "content"])},
    {"name": "browse_folders", "description": "List Design Studio folders (root 2).",
     "parameters": _obj({"root": _INT, "maxReturn": _MAX}, [])},
    {"name": "create_form", "description": "Create a form in a Design Studio folder. "
     "FirstName, LastName and Email are added automatically.",
     "parameters": _obj({"name": {"type": "string"}, "description": {"type": "string"},
                         "folder": {"type": "object", "properties": {
                             "id": _INT, "type": {"type": "string"}}}}, ["name", "folder"])},
    {"name": "add_field_to_form", "description": "Add a lead field to a form.",
     "parameters": _obj({"id": _INT, "fieldId": {"type": "string"},
                         "label": {"type": "string"}, "required": {"type": "boolean"}},
                        ["id", "fieldId"])},
    {"name": "approve_snippet", "description": "Approve a draft snippet so it goes live.",
     "parameters": _obj({"id": _INT}, ["id"])},
]


async def _noop() -> None:
    return None
