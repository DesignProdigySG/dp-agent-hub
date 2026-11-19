"""Async Marketo REST + Bulk API client. Every request goes through the shared governor."""

import asyncio
import csv
import io
import json
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.marketo.governor import RateGovernor

log = logging.getLogger(__name__)

TOKEN_ERRORS = {"601", "602"}  # access token invalid / expired
RETRYABLE_ERRORS = {"606", "615"}  # rate limit / concurrency limit (should be rare behind governor)
# Network blips (timeouts, dropped connections, gateway errors) are retried with backoff, but
# only for requests that are safe to repeat: reads and the token request. A write that timed
# out may have been applied, so it is never sent twice.
NET_RETRY_DELAYS = (2, 5, 15, 30)
GATEWAY_ERRORS = {502, 503, 504}


class MarketoError(RuntimeError):
    def __init__(self, errors: list[dict[str, Any]]):
        self.errors = errors
        super().__init__("; ".join(f"{e.get('code')}: {e.get('message')}" for e in errors))


class MarketoRestClient:
    def __init__(self, base_url: str, client_id: str, client_secret: str, governor: RateGovernor):
        self.base_url = base_url.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._governor = governor
        self._http = httpx.AsyncClient(base_url=self.base_url, timeout=60)
        self._token: str | None = None
        self._token_expires = 0.0
        self._token_lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _send(self, method: str, make, *, safe: bool) -> httpx.Response:
        """One HTTP exchange through the governor, retried on network errors when `safe`."""
        delays = NET_RETRY_DELAYS if safe else ()
        for attempt in range(len(delays) + 1):
            try:
                resp = await self._governor.run("rest", make)
                if resp.status_code not in GATEWAY_ERRORS or attempt == len(delays):
                    return resp
                problem = f"HTTP {resp.status_code}"
            except httpx.TransportError as e:
                if attempt == len(delays):
                    raise
                problem = type(e).__name__
            log.warning("Marketo %s: %s; retrying in %ss", method, problem, delays[attempt])
            await asyncio.sleep(delays[attempt])
        raise AssertionError("unreachable")

    async def _access_token(self, force: bool = False) -> str:
        async with self._token_lock:
            if force or not self._token or time.monotonic() > self._token_expires - 60:
                # Credentials go in a form body, never the URL: URLs end up in error messages
                # and logs (Marketo supports POST for the identity endpoint).
                resp = await self._send(
                    "POST token",
                    lambda: self._http.post(
                        "/identity/oauth/token",
                        data={
                            "grant_type": "client_credentials",
                            "client_id": self._client_id,
                            "client_secret": self._client_secret,
                        },
                    ),
                    safe=True,
                )
                if resp.status_code in (400, 401):
                    body = resp.json() if "json" in resp.headers.get("content-type", "") else {}
                    raise MarketoError([{"code": str(resp.status_code), "message": (
                        f"Marketo rejected the client ID / secret: "
                        f"{body.get('error_description') or body.get('error') or 'unauthorized'}"
                    )}])
                resp.raise_for_status()
                body = resp.json()
                self._token = body["access_token"]
                self._token_expires = time.monotonic() + int(body.get("expires_in", 3600))
            return self._token

    async def request(self, method: str, path: str, *, raw: bool = False, **kwargs) -> Any:
        refresh = False
        for attempt in range(4):
            token = await self._access_token(force=refresh)
            refresh = False
            headers = {"Authorization": f"Bearer {token}"}
            resp = await self._send(
                method, lambda h=headers: self._http.request(method, path, headers=h, **kwargs),
                safe=method == "GET")
            resp.raise_for_status()
            if raw:
                return resp.text
            body = resp.json()
            if body.get("success", True):
                return body
            errors = body.get("errors", [])
            codes = {str(e.get("code")) for e in errors}
            if codes & TOKEN_ERRORS:
                refresh = True
                continue
            if codes & RETRYABLE_ERRORS:
                await asyncio.sleep(2**attempt)
                continue
            raise MarketoError(errors)
        raise MarketoError([{"code": "retry", "message": f"gave up on {method} {path}"}])

    # --- Leads --------------------------------------------------------------------------

    async def get_leads(self, filter_type: str, values: list[str], fields: list[str]) -> list[dict]:
        body = await self.request(
            "GET",
            "/rest/v1/leads.json",
            params={
                "filterType": filter_type,
                "filterValues": ",".join(values),
                "fields": ",".join(fields),
            },
        )
        return body.get("result", [])

    async def update_leads(self, leads: list[dict]) -> list[dict]:
        results = []
        for i in range(0, len(leads), 300):  # API max batch size
            body = await self.request(
                "POST",
                "/rest/v1/leads.json",
                json={"action": "updateOnly", "lookupField": "id", "input": leads[i : i + 300]},
            )
            results.extend(body.get("result", []))
        return results

    async def merge_leads(self, winner_id: int, loser_ids: list[int]) -> None:
        await self.request(
            "POST",
            f"/rest/v1/leads/{winner_id}/merge.json",
            params={"leadIds": ",".join(map(str, loser_ids))},
        )

    async def add_leads_to_list(self, list_id: int, lead_ids: list[int]) -> list[dict]:
        results = []
        for i in range(0, len(lead_ids), 300):
            body = await self.request(
                "POST",
                f"/rest/v1/lists/{list_id}/leads.json",
                json={"input": [{"id": lid} for lid in lead_ids[i : i + 300]]},
            )
            results.extend(body.get("result", []))
        return results

    async def list_leads(self, list_id: int, batch_size: int, fields: list[str]) -> list[dict]:
        """The first `batch_size` (max 300) members of a static list."""
        body = await self.request("GET", f"/rest/v1/lists/{list_id}/leads.json",
                                  params={"batchSize": max(1, min(batch_size, 300)),
                                          "fields": ",".join(fields)})
        return body.get("result", [])

    async def list_membership(self, list_id: int, lead_ids: list[int],
                              max_pages: int = 20) -> dict[int, bool]:
        """Whether each lead is on a static list. Uses ismember; if the API user's role
        doesn't allow it (603), reads the list's members instead (up to max_pages x 300)."""
        try:
            body = await self.request("GET", f"/rest/v1/lists/{list_id}/leads/ismember.json",
                                      params={"id": ",".join(map(str, lead_ids))})
            return {int(r["id"]): r.get("status") == "memberof" for r in body.get("result", [])}
        except MarketoError as e:
            if not any(str(x.get("code")) == "603" for x in e.errors):
                raise
        wanted, found, token = set(lead_ids), set(), None
        for _ in range(max_pages):
            params = {"batchSize": 300, "fields": "id",
                      **({"nextPageToken": token} if token else {})}
            body = await self.request("GET", f"/rest/v1/lists/{list_id}/leads.json", params=params)
            found |= {int(r["id"]) for r in body.get("result", [])} & wanted
            token = body.get("nextPageToken")
            if found == wanted or not token or not body.get("result"):
                break
        return {lid: lid in found for lid in lead_ids}

    async def remove_leads_from_list(self, list_id: int, lead_ids: list[int]) -> list[dict]:
        body = await self.request("DELETE", f"/rest/v1/lists/{list_id}/leads.json",
                                  json={"input": [{"id": lid} for lid in lead_ids]})
        return body.get("result", [])

    async def request_campaign(self, campaign_id: int, lead_ids: list[int],
                               tokens: list[dict[str, str]] | None = None) -> list[dict]:
        """Request (trigger) a smart campaign for leads. Marketo answers HTTP 200 with
        success=false on errors; `request` raises MarketoError for those."""
        try:
            body = await self.request("POST", f"/rest/v1/campaigns/{campaign_id}/trigger.json",
                                      json={"input": {"leads": [{"id": lid} for lid in lead_ids],
                                                      **({"tokens": tokens} if tokens else {})}})
        except MarketoError as e:
            if any(str(x.get("code")) == "603" for x in e.errors):
                raise MarketoError([{"code": "603", "message": (
                    f"Marketo refused to request campaign {campaign_id}: the API user's role "
                    "needs the Execute Campaign permission")}]) from None
            raise
        return body.get("result", [])

    async def get_lead_activities(
        self, activity_type_ids: list[int], since: datetime, lead_ids: list[int] | None = None
    ) -> list[dict]:
        token_body = await self.request(
            "GET",
            "/rest/v1/activities/pagingtoken.json",
            params={"sinceDatetime": since.isoformat()},
        )
        page_token = token_body["nextPageToken"]
        activities: list[dict] = []
        while True:
            params: dict[str, Any] = {
                "nextPageToken": page_token,
                "activityTypeIds": ",".join(map(str, activity_type_ids)),
            }
            if lead_ids:
                params["leadIds"] = ",".join(map(str, lead_ids[:30]))
            body = await self.request("GET", "/rest/v1/activities.json", params=params)
            activities.extend(body.get("result", []))
            if not body.get("moreResult") or len(activities) >= 2000:
                return activities
            page_token = body["nextPageToken"]

    async def paging_token(self, since: datetime) -> str:
        body = await self.request("GET", "/rest/v1/activities/pagingtoken.json",
                                  params={"sinceDatetime": since.isoformat()})
        return body["nextPageToken"]

    async def activities_page(self, page_token: str, type_ids: list[int]) -> dict:
        """One page of activities: {"result": [...], "nextPageToken": ..., "moreResult": ...}."""
        return await self.request("GET", "/rest/v1/activities.json", params={
            "nextPageToken": page_token,
            "activityTypeIds": ",".join(map(str, type_ids[:10])),  # API max is 10
        })

    async def activity_types(self) -> dict[int, str]:
        body = await self.request("GET", "/rest/v1/activities/types.json")
        return {int(t["id"]): t["name"] for t in body.get("result", [])}

    async def asset_call(self, call: dict[str, Any]) -> Any:
        """One Asset API operation (see asset_api.split_args): form fields with objects as
        JSON, multipart files for `files`, or a JSON body."""
        def form_value(v: Any) -> Any:
            return json.dumps(v) if isinstance(v, (dict, list)) else (
                str(v).lower() if isinstance(v, bool) else v)

        kwargs: dict[str, Any] = {"params": {k: form_value(v) for k, v in call["query"].items()}}
        body = call["body"]
        if call["method"] != "GET" and body:
            if call["encoding"] == "json":
                kwargs["json"] = body
            else:
                kwargs["data"] = {k: form_value(v) for k, v in body.items()
                                  if k not in call.get("files", [])}
                if call["encoding"] == "multipart" or call.get("files"):
                    kwargs["files"] = {k: (f"{k}.html", str(body[k]).encode(), "text/html")
                                       for k in call.get("files", []) if k in body}
                    if not kwargs["files"]:  # multipart without a file part
                        kwargs["files"] = {k: (None, str(v)) for k, v in kwargs.pop(
                            "data").items()}
        elif call["method"] == "GET" and body:
            kwargs["params"].update({k: form_value(v) for k, v in body.items()})
        try:
            return await self.request(call["method"], call["path"], **kwargs)
        except MarketoError as e:
            if any(str(x.get("code")) == "603" for x in e.errors):
                raise MarketoError([{"code": "603", "message": (
                    f"Marketo refused {call['method']} {call['path']}: the API user's role "
                    "doesn't allow it. In Marketo Admin > Users & Roles, give the API role "
                    "Read-Write Assets and access to the workspace (Design Studio).")}]) \
                    from None
            raise

    async def lead_field_names(self) -> list[str]:
        body = await self.request("GET", "/rest/v1/leads/describe2.json")
        return [f["name"] for f in body["result"][0]["fields"]]

    # --- Bulk export --------------------------------------------------------------------

    async def bulk_create(self, kind: str, body: dict[str, Any]) -> str:
        """Create and enqueue a bulk export job (kind: leads | activities); returns its id."""
        created = await self.request("POST", f"/bulk/v1/{kind}/export/create.json", json=body)
        export_id = created["result"][0]["exportId"]
        await self.request("POST", f"/bulk/v1/{kind}/export/{export_id}/enqueue.json")
        return export_id

    async def bulk_rows(self, kind: str, export_id: str, poll_s: float = 15,
                        timeout_s: float = 3600) -> list[dict]:
        """Wait for a bulk job and download its CSV. Safe to call again for the same job
        (e.g. after a restart): Marketo keeps finished files for 7 days."""
        for _ in range(max(1, int(timeout_s / poll_s))):
            status = await self.request("GET", f"/bulk/v1/{kind}/export/{export_id}/status.json")
            state = status["result"][0]["status"]
            if state == "Completed":
                break
            if state in ("Failed", "Cancelled"):
                raise MarketoError([{"code": "bulk", "message": f"export {export_id} {state}: "
                                     f"{status['result'][0].get('errorMsg', '')}"}])
            await asyncio.sleep(poll_s)
        else:
            raise MarketoError([{"code": "bulk", "message": f"export {export_id} timed out"}])
        text = await self.request("GET", f"/bulk/v1/{kind}/export/{export_id}/file.json",
                                  raw=True)
        return list(csv.DictReader(io.StringIO(text)))

    async def bulk_export_leads(self, fields: list[str], days: int = 30) -> list[dict]:
        """Export leads created in the last `days` (Bulk API caps a filter at 31 days)."""
        end = datetime.now(UTC)
        start = end - timedelta(days=min(days, 31))
        export_id = await self.bulk_create("leads", {
            "fields": fields, "format": "CSV",
            "filter": {"createdAt": {"startAt": start.isoformat(), "endAt": end.isoformat()}}})
        return await self.bulk_rows("leads", export_id, poll_s=10, timeout_s=1200)

    async def activity_export_start(self, start: datetime, end: datetime,
                                    type_ids: list[int]) -> str:
        """Bulk activity export for one window of at most 31 days."""
        return await self.bulk_create("activities", {
            "format": "CSV", "filter": {
                "createdAt": {"startAt": start.isoformat(), "endAt": end.isoformat()},
                "activityTypeIds": type_ids}})
