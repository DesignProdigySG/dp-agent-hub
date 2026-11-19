"""Azure Data Lake Storage Gen2 archive.

Raw activity batches and daily KPI snapshots are written as gzipped JSON Lines under
`<prefix>/<kind>/date=YYYY-MM-DD/`, a Hive-style layout that Synapse, Fabric, Databricks and
Spark read directly. Archiving is best-effort: a failure is reported in status but never
stops ingestion, because Postgres stays the system of record.
"""

import asyncio
import gzip
import json
import logging
from datetime import UTC, date, datetime
from typing import Any

from app.config import Settings, get_settings

log = logging.getLogger(__name__)


class LakeArchiver:
    def __init__(self) -> None:
        self._fs = None
        self._config_key: tuple | None = None
        self.last_error = ""
        self.last_write: str = ""

    @staticmethod
    def enabled(settings: Settings | None = None) -> bool:
        s = settings or get_settings()
        if not s.adls_enabled:
            return False
        if s.adls_auth == "connection_string":
            return bool(s.adls_connection_string)
        return bool(s.adls_account_url and s.azure_tenant_id and s.azure_client_id
                    and s.azure_client_secret)

    def reset(self) -> None:
        self._fs = None
        self._config_key = None

    def _filesystem(self, s: Settings):
        key = (s.adls_auth, s.adls_connection_string, s.adls_account_url, s.adls_filesystem,
               s.azure_tenant_id, s.azure_client_id, s.azure_client_secret)
        if self._fs is not None and key == self._config_key:
            return self._fs
        from azure.core.exceptions import ResourceExistsError
        from azure.storage.filedatalake import DataLakeServiceClient

        if s.adls_auth == "connection_string":
            service = DataLakeServiceClient.from_connection_string(s.adls_connection_string)
        else:
            from azure.identity import ClientSecretCredential

            credential = ClientSecretCredential(s.azure_tenant_id, s.azure_client_id,
                                                s.azure_client_secret)
            service = DataLakeServiceClient(account_url=s.adls_account_url,
                                            credential=credential)
        fs = service.get_file_system_client(s.adls_filesystem)
        try:
            fs.create_file_system()
        except ResourceExistsError:
            pass
        self._fs, self._config_key = fs, key
        return fs

    def _path(self, s: Settings, kind: str, day: date, name: str) -> str:
        prefix = s.adls_path_prefix.strip("/")
        return f"{prefix + '/' if prefix else ''}{kind}/date={day.isoformat()}/{name}"

    def _write(self, kind: str, day: date, name: str, records: list[dict[str, Any]]) -> str:
        s = get_settings()
        body = "\n".join(json.dumps(r, default=str) for r in records).encode()
        path = self._path(s, kind, day, f"{name}.jsonl.gz")
        file = self._filesystem(s).get_file_client(path)
        file.upload_data(gzip.compress(body), overwrite=True)
        return path

    async def write(self, kind: str, records: list[dict[str, Any]], *, day: date | None = None,
                    name: str | None = None) -> str | None:
        if not records or not self.enabled():
            return None
        day = day or datetime.now(UTC).date()
        name = name or datetime.now(UTC).strftime("%H%M%S%f")
        try:
            path = await asyncio.to_thread(self._write, kind, day, name, records)
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"[:300]
            log.warning("Data Lake write failed: %s", self.last_error)
            self.reset()
            return None
        self.last_error, self.last_write = "", path
        return path

    async def test(self) -> dict:
        s = get_settings()
        if not self.enabled(s):
            return {"ok": False, "error": "Data Lake archiving is off or missing credentials"}

        def probe() -> str:
            fs = self._filesystem(s)
            path = self._path(s, "_healthcheck", datetime.now(UTC).date(), "probe.txt")
            f = fs.get_file_client(path)
            f.upload_data(b"ok", overwrite=True)
            f.delete_file()
            return path

        try:
            path = await asyncio.to_thread(probe)
        except Exception as e:
            self.reset()
            return {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}
        return {"ok": True, "detail": f"wrote and removed {path} in {s.adls_filesystem}"}
