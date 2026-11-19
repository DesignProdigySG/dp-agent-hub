"""Marketo Data Streams via the Adobe I/O Events Journaling API.

Data Streams events are delivered through Adobe I/O Events. We use the journal (pull) rather
than a webhook, so the hub needs no public endpoint: start at the registration's journal URL,
follow the `Link: rel="next"` header, and on `204 No Content` (caught up) wait `retry-after`
seconds before polling the same next link again. The journal keeps about 7 days of events, so
a hub that is down for less than that loses nothing.

Auth is an Adobe IMS OAuth server-to-server token from the Developer Console project.
"""

import logging
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

import httpx

from app.config import Settings

log = logging.getLogger(__name__)

IMS_TOKEN_URL = "https://ims-na1.adobelogin.com/ims/token/v3"


class JournalClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None):
        # pasted values often carry stray whitespace, which is illegal in an HTTP header
        self.client_id = settings.adobe_client_id.strip()
        self._secret = settings.adobe_client_secret.strip()
        self.org_id = settings.adobe_org_id.strip()
        self.scopes = settings.adobe_ims_scopes.strip()
        self.start_url = settings.datastreams_journal_url.strip()
        self._http = http or httpx.AsyncClient(timeout=60)
        self._token: str | None = None
        self._expires = 0.0

    async def aclose(self) -> None:
        await self._http.aclose()

    async def token(self, force: bool = False) -> str:
        if force or not self._token or time.monotonic() > self._expires - 120:
            resp = await self._http.post(IMS_TOKEN_URL, data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self._secret,
                "scope": self.scopes,
            })
            resp.raise_for_status()
            body = resp.json()
            self._token = body["access_token"]
            self._expires = time.monotonic() + int(body.get("expires_in", 3600))
        return self._token

    async def fetch(self, url: str | None) -> tuple[list[dict], str, int]:
        """Fetch one journal page. Returns (entries, next_url, retry_after_seconds)."""
        url = url or self.start_url
        for attempt in range(2):
            resp = await self._http.get(url, headers={
                "Authorization": f"Bearer {await self.token(force=attempt > 0)}",
                "x-api-key": self.client_id,
                "x-ims-org-id": self.org_id,
                "Accept": "application/json",
            })
            # Refresh once: tokens expire early (401), and a token issued before the Developer
            # Console project changed (e.g. I/O Management API added) is refused (403).
            if resp.status_code in (401, 403) and attempt == 0:
                continue
            break
        next_link = resp.links.get("next", {}).get("url")
        next_url = urljoin(url, next_link) if next_link else url
        if resp.status_code == 204:
            return [], next_url, int(resp.headers.get("retry-after", "10") or 10)
        resp.raise_for_status()
        body = resp.json()
        return body.get("events", []), next_url, 0


def _attrs(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):  # Marketo style: [{"name": ..., "value": ...}]
        return {str(a.get("name") or a.get("apiName")): a.get("value") for a in value
                if isinstance(a, dict)}
    return {}


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _time(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):  # epoch millis
        return datetime.fromtimestamp(value / 1000, UTC)
    if isinstance(value, str) and value:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        except ValueError:
            pass
    return datetime.now(UTC)


def normalize_activity(record: dict, source: str,
                       type_names: dict[int, str] | None = None) -> dict | None:
    """Map a REST activity or a Data Streams journal entry onto marketo_activity columns.

    Data Streams payloads are CloudEvents whose `data` carries the activity; field names are
    read defensively and the full record is always kept in `raw`.
    """
    event = record.get("event", record) if source == "datastreams" else record
    data = event.get("data", event) if isinstance(event, dict) else {}
    if not isinstance(data, dict):
        data = {"value": data}
    external = (event.get("id") or record.get("position") or data.get("marketoGUID")
                or data.get("id"))
    if external is None:
        return None
    type_id = _int(data.get("activityTypeId"))
    type_name = data.get("activityType") or data.get("activityTypeName")
    if isinstance(type_name, dict):
        type_name = type_name.get("name")
    if not type_name and type_id is not None and type_names:
        type_name = type_names.get(type_id)
    return {
        "source": source,
        "external_id": str(external),
        "lead_id": _int(data.get("leadId") or data.get("personId")),
        "activity_type_id": type_id,
        "activity_type": str(type_name or event.get("type") or "unknown")[:200],
        "occurred_at": _time(data.get("activityDate") or event.get("time")),
        "primary_attribute_value": (str(data["primaryAttributeValue"])
                                    if data.get("primaryAttributeValue") is not None else None),
        "campaign_id": _int(data.get("campaignId")),
        "attributes": _attrs(data.get("attributes")),
        "raw": record,
        "ingested_at": datetime.now(UTC),
    }
