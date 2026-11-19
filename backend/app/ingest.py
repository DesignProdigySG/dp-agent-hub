"""Continuously ingests Marketo activities into the database (and the Data Lake archive).

Source selection (`activity_source`):
  auto        -> Data Streams if configured, else REST polling in live mode, else demo data
  datastreams -> Adobe I/O Events journal (see marketo/datastreams.py)
  rest        -> /rest/v1/activities.json with a persisted paging token
  off         -> nothing
Each source keeps a cursor in ingest_cursor, so a restart resumes where it stopped.
"""

import asyncio
import logging
import random
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete
from sqlalchemy.dialects import postgresql, sqlite
from sqlmodel import select

from app.config import Settings, get_settings
from app.db import IngestCursor, MarketoActivity, get_engine, session
from app.marketo.datastreams import JournalClient, normalize_activity
from app.marketo.gateway import DemoMarketo, LiveMarketo

log = logging.getLogger(__name__)

MAX_PAGES_PER_POLL = 20
DEMO_TYPES = [(1, "Visit Webpage", ["/pricing", "/blog/ai-ops", "/integrations/marketo",
                                    "/case-studies", "/demo"]),
              (2, "Fill Out Form", ["Demo Request", "Webinar Registration", "Contact Us"]),
              (10, "Open Email", ["Newsletter - Nov", "Q4 Launch", "Webinar Reminder"]),
              (11, "Click Email", ["Newsletter - Nov", "Q4 Launch"]),
              (7, "Email Delivered", ["Newsletter - Nov", "Q4 Launch", "Webinar Reminder"])]


def resolve_source(s: Settings) -> str:
    if s.activity_source != "auto":
        return s.activity_source
    if s.datastreams_configured:
        return "datastreams"
    if s.marketo_mode == "live" and s.marketo_configured:
        return "rest"
    return "demo" if s.marketo_mode == "demo" else "off"


def insert_activities(rows: list[dict[str, Any]]) -> int:
    """Insert, skipping (source, external_id) duplicates. Returns rows actually inserted."""
    if not rows:
        return 0
    engine = get_engine()
    dialect = postgresql if engine.dialect.name == "postgresql" else sqlite
    table = MarketoActivity.__table__
    inserted = 0
    with engine.begin() as conn:
        for i in range(0, len(rows), 500):
            stmt = (dialect.insert(table).values(rows[i:i + 500])
                    .on_conflict_do_nothing(index_elements=["source", "external_id"])
                    .returning(table.c.id))  # rowcount is unreliable for batched inserts
            inserted += len(conn.execute(stmt).fetchall())
    return inserted


def purge_older_than(days: int) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=days)
    with get_engine().begin() as conn:
        result = conn.execute(delete(MarketoActivity.__table__)
                              .where(MarketoActivity.__table__.c.occurred_at < cutoff))
    return result.rowcount or 0


class ActivityIngestor:
    def __init__(self, deps) -> None:
        self.deps = deps
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self._journal: JournalClient | None = None
        self._journal_key: tuple | None = None
        self._type_names: dict[int, str] = {}
        self.source = "off"
        self.last_error = ""
        self.last_poll_at: datetime | None = None
        self.last_count = 0

    # --- lifecycle --------------------------------------------------------------------------

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        if self._journal:
            await self._journal.aclose()

    def kick(self) -> None:
        """Re-evaluate the source now (called when settings change)."""
        self._wake.set()

    async def _sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._wake.wait(), timeout=max(seconds, 1))
        except TimeoutError:
            pass
        self._wake.clear()

    async def _run(self) -> None:
        backoff = 5
        while True:
            s = get_settings()
            self.source = resolve_source(s)
            if self.source == "off":
                await self._sleep(s.activity_poll_seconds)
                continue
            try:
                delay = await getattr(self, f"_poll_{self.source}")(s)
                self.last_error, backoff = "", 5
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {e}"[:400]
                log.warning("activity ingestion (%s) failed: %s", self.source, self.last_error)
                await asyncio.to_thread(self._save_cursor, self.source, None, 0, self.last_error)
                delay, backoff = backoff, min(backoff * 2, 600)
            await self._sleep(delay)

    # --- persistence ------------------------------------------------------------------------

    def _load_cursor(self, source: str) -> str:
        with session() as s:
            row = s.get(IngestCursor, source)
        return row.cursor if row else ""

    def _save_cursor(self, source: str, cursor: str | None, count: int, error: str = "") -> None:
        with session() as s:
            row = s.get(IngestCursor, source) or IngestCursor(source=source)
            if cursor is not None:
                row.cursor = cursor
            row.last_poll_at, row.last_count, row.last_error = datetime.now(UTC), count, error
            row.total_count += count
            s.add(row)
            s.commit()

    async def _store(self, source: str, rows: list[dict], cursor: str | None) -> int:
        inserted = await asyncio.to_thread(insert_activities, rows)
        await asyncio.to_thread(self._save_cursor, source, cursor, inserted)
        self.last_poll_at, self.last_count = datetime.now(UTC), inserted
        if inserted:
            await self.deps.lake.write("activities", rows,
                                       name=f"{source}-{datetime.now(UTC):%H%M%S%f}")
        return inserted

    # --- sources ----------------------------------------------------------------------------

    def _journal_client(self, s: Settings) -> JournalClient:
        key = (s.adobe_client_id, s.adobe_client_secret, s.adobe_org_id, s.adobe_ims_scopes,
               s.datastreams_journal_url)
        if self._journal is None or key != self._journal_key:
            self._journal, self._journal_key = JournalClient(s), key
        return self._journal

    async def _poll_datastreams(self, s: Settings) -> float:
        if not s.datastreams_configured:
            raise RuntimeError("Data Streams selected but the Adobe credentials or journal "
                               "URL are missing")
        client = self._journal_client(s)
        url = await asyncio.to_thread(self._load_cursor, "datastreams") or s.datastreams_journal_url
        total = 0
        for _ in range(MAX_PAGES_PER_POLL):
            entries, next_url, retry_after = await client.fetch(url)
            rows = [r for e in entries if (r := normalize_activity(e, "datastreams"))]
            total += await self._store("datastreams", rows, next_url)
            url = next_url
            if retry_after:  # caught up with the journal
                return retry_after
        return 1  # more pages waiting; come straight back

    async def _poll_rest(self, s: Settings) -> float:
        marketo = self.deps.marketo
        if not isinstance(marketo, LiveMarketo):
            raise RuntimeError("REST activity polling needs Marketo mode set to live")
        rest = marketo.rest
        if not self._type_names:
            self._type_names = await rest.activity_types()
        type_ids = [int(t) for t in s.rest_activity_type_ids.split(",") if t.strip()]
        token = await asyncio.to_thread(self._load_cursor, "rest")
        if not token:
            token = await rest.paging_token(datetime.now(UTC) - timedelta(days=1))
        for _ in range(MAX_PAGES_PER_POLL):
            body = await rest.activities_page(token, type_ids)
            rows = [r for a in body.get("result", []) or []
                    if (r := normalize_activity(a, "rest", self._type_names))]
            token = body.get("nextPageToken", token)
            await self._store("rest", rows, token)
            if not body.get("moreResult"):
                break
        return s.activity_poll_seconds

    async def _poll_demo(self, s: Settings) -> float:
        marketo = self.deps.marketo
        if not isinstance(marketo, DemoMarketo):
            raise RuntimeError("demo activity source needs Marketo mode set to demo")
        lead_ids = list(marketo.leads)
        now = datetime.now(UTC)
        rows = []
        for _ in range(random.randint(4, 18)):
            type_id, name, assets = random.choice(DEMO_TYPES)
            ext = f"demo-{now:%Y%m%d%H%M%S%f}-{random.getrandbits(32):08x}"
            rows.append(normalize_activity({
                "id": ext, "leadId": random.choice(lead_ids), "activityTypeId": type_id,
                "activityType": name, "primaryAttributeValue": random.choice(assets),
                "activityDate": (now - timedelta(seconds=random.randint(0, 300))).isoformat(),
            }, "demo"))
        await self._store("demo", [r for r in rows if r], None)
        return max(s.activity_poll_seconds, 15)

    # --- status -----------------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        with session() as s:
            cursors = {c.source: c for c in s.exec(select(IngestCursor)).all()}
        return {
            "source": self.source,
            "last_poll_at": self.last_poll_at.isoformat() if self.last_poll_at else None,
            "last_count": self.last_count,
            "last_error": self.last_error,
            "sources": {k: {"last_poll_at": v.last_poll_at.isoformat() if v.last_poll_at
                            else None, "total": v.total_count, "last_error": v.last_error,
                            "has_cursor": bool(v.cursor)} for k, v in cursors.items()},
            "lake": {"enabled": self.deps.lake.enabled(), "last_write": self.deps.lake.last_write,
                     "last_error": self.deps.lake.last_error},
        }
