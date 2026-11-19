"""Configuration.

Two kinds of settings live on one model:

* Bootstrap settings (DATABASE_URL, HUB_SECRET_KEY, ADMIN_PASSWORD, ...) come only from the
  environment / .env, because the app needs them before it can reach its own database.
* Runtime settings (Marketo, LLMs, Data Streams, Data Lake, ...) take their default from the
  environment but can be overridden in the UI; overrides are stored encrypted in the database
  (see settings_store.py) and applied with `apply_overrides`.
"""

import logging
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent.parent
MUNCHKIN_RE = re.compile(r"\d{3}-[A-Z]{3}-\d{3}")
EMAIL_RE = re.compile(r"[^@\s,<>]+@[^@\s,<>]+\.[^@\s,<>]+")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIR.parent / ".env", BACKEND_DIR / ".env"),
        extra="ignore",
        hide_input_in_errors=True,  # never echo credentials into logs
    )

    # --- Bootstrap (environment only) -----------------------------------------------------
    # postgresql://user:pass@host:5432/db. Empty = SQLite in data_dir (dev and tests).
    database_url: str = ""
    # Fernet key that encrypts secrets at rest. Empty = generated once into data_dir/secret.key.
    hub_secret_key: str = ""
    # Sets the admin password on first start if none is stored yet.
    admin_password: str = ""
    cookie_secure: bool = False  # set true when served over HTTPS
    data_dir: Path = BACKEND_DIR / "data"
    # Your brand pack for the Designer tools (optional; see backend/brand/README.md).
    brand_dir: Path = BACKEND_DIR / "brand"
    cors_origins: list[str] = ["http://localhost:5180", "http://127.0.0.1:5180"]

    # --- Runtime (environment default, editable in Settings) ---------------------------------
    public_read_access: bool = False  # let signed-out viewers see the board (never settings)

    # "demo" runs every agent against an in-memory fake Marketo; "live" uses real credentials.
    marketo_mode: Literal["demo", "live"] = "demo"
    # LaunchPoint Custom Service credentials, shared by the REST/Bulk API and the MCP server
    marketo_munchkin_id: str = ""  # e.g. 123-ABC-456
    marketo_client_id: str = ""
    marketo_client_secret: str = ""
    marketo_mcp_url: str = "https://marketo-mcp.adobe.io/mcp"
    # Where Marketo opens in a browser, up to (not including) an asset's code like PG1234A1:
    # https://app-ab12.marketo.com/#  or  https://experience.adobe.com/#/@org/so:123-ABC-456/
    # marketo-engage/classic/   (app/marketo/links.py)
    marketo_ui_url: str = ""

    # Rate governor, shared across REST and MCP
    governor_calls: int = 100
    governor_window_s: float = 20.0
    governor_max_concurrent: int = 10
    governor_daily_quota: int = 50_000

    # LLM router. Models are "provider/model"; anthropic/* goes through the Anthropic SDK,
    # everything else through LiteLLM (openai/..., gemini/..., azure/..., ollama/...).
    llm_routing: Literal["auto", "fixed"] = "auto"
    llm_fast_model: str = "anthropic/claude-haiku-5-5"
    llm_standard_model: str = "anthropic/claude-sonnet-5-5"
    llm_strong_model: str = "anthropic/claude-opus-5-5"
    llm_fallback_models: str = ""  # comma-separated, tried after the tier's model
    llm_daily_budget_usd: float = 0.0  # 0 = no cap
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    azure_openai_api_key: str = ""
    azure_openai_endpoint: str = ""
    ollama_base_url: str = "http://localhost:11434"

    # Knowledge search. Embeddings go through LiteLLM ("provider/model"); Anthropic has no
    # embeddings model, so Claude users typically pair it with Voyage or OpenAI. Empty =
    # keyword search only.
    embedding_model: str = ""  # e.g. voyage/voyage-3.5, openai/text-embedding-3-small
    voyage_api_key: str = ""

    # Activity ingestion: Marketo Data Streams (Adobe I/O Events journal) or REST polling
    activity_source: Literal["auto", "datastreams", "rest", "off"] = "auto"
    activity_poll_seconds: int = 60
    activity_retention_days: int = 365
    rest_activity_type_ids: str = "1,2,6,7,9,10,11,12,13,22"
    adobe_org_id: str = ""
    adobe_client_id: str = ""
    adobe_client_secret: str = ""
    adobe_ims_scopes: str = "AdobeID,openid,read_organizations,adobeio_api"
    datastreams_journal_url: str = ""

    # Azure Data Lake Storage Gen2 archive of raw events and daily snapshots
    adls_enabled: bool = False
    adls_auth: Literal["connection_string", "service_principal"] = "connection_string"
    adls_connection_string: str = ""
    adls_account_url: str = ""  # https://<account>.dfs.core.windows.net
    adls_filesystem: str = "marketo-agent-hub"
    adls_path_prefix: str = "raw"
    azure_tenant_id: str = ""
    azure_client_id: str = ""
    azure_client_secret: str = ""

    # Human-in-the-loop notifications (approval requests, optionally failed tasks)
    hub_public_url: str = "http://localhost:5180"  # where links in messages point
    approval_link_hours: int = 24
    notify_task_failures: bool = False
    email_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls"
    smtp_username: str = ""
    smtp_password: str = ""
    email_from: str = ""
    email_to: str = ""  # comma-separated reviewers

    # Paid verification used by the Data Doctor's skills (only when the skill is attached)
    zerobounce_api_key: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    verify_max_per_scan: int = 200  # paid checks per scan, emails and phones each

    # Operations
    agent_pacing_s: float = 1.5
    snapshot_hour_utc: int = 1  # daily KPI snapshot of the previous day runs after this hour

    @field_validator("marketo_munchkin_id")
    @classmethod
    def _check_munchkin(cls, v: str) -> str:
        v = v.strip().upper()
        if v and not MUNCHKIN_RE.fullmatch(v):
            raise ValueError(
                "Munchkin ID should look like 123-ABC-456 (Admin > Munchkin), "
                "not a client ID or URL"
            )
        return v

    @field_validator("hub_public_url")
    @classmethod
    def _check_public_url(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if v and not re.fullmatch(r"https?://[^\s/]+(/\S*)?", v):
            raise ValueError("use the hub's address, e.g. https://hub.example.com")
        return v

    @field_validator("approval_link_hours")
    @classmethod
    def _check_link_hours(cls, v: int) -> int:
        if not 1 <= v <= 168:
            raise ValueError("links can last 1-168 hours")
        return v

    @field_validator("email_to", "email_from")
    @classmethod
    def _check_addresses(cls, v: str) -> str:
        addresses = [a.strip() for a in v.split(",") if a.strip()]
        if any(not EMAIL_RE.fullmatch(a) for a in addresses):
            raise ValueError("use email addresses separated by commas")
        return ", ".join(addresses)

    @field_validator("snapshot_hour_utc")
    @classmethod
    def _check_hour(cls, v: int) -> int:
        if not 0 <= v <= 23:
            raise ValueError("snapshot hour must be 0-23")
        return v

    @property
    def marketo_rest_url(self) -> str:
        return f"https://{self.marketo_munchkin_id}.mktorest.com"

    @property
    def email_recipients(self) -> list[str]:
        return [a.strip() for a in self.email_to.split(",") if a.strip()]

    @property
    def email_ready(self) -> bool:
        return (self.email_enabled and bool(self.smtp_host and self.email_from)
                and bool(self.email_recipients))

    @property
    def marketo_configured(self) -> bool:
        return bool(self.marketo_munchkin_id and self.marketo_client_id
                    and self.marketo_client_secret)

    @property
    def datastreams_configured(self) -> bool:
        return bool(self.datastreams_journal_url and self.adobe_client_id
                    and self.adobe_client_secret and self.adobe_org_id)

    @property
    def sqlalchemy_url(self) -> str:
        if not self.database_url:
            return f"sqlite:///{self.data_dir / 'hub.db'}"
        url = self.database_url
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url

    @property
    def is_postgres(self) -> bool:
        return self.sqlalchemy_url.startswith("postgresql")

    @property
    def libpq_url(self) -> str:
        """Plain postgresql:// URL for psycopg / the LangGraph Postgres checkpointer."""
        return self.sqlalchemy_url.replace("postgresql+psycopg://", "postgresql://", 1)


BOOTSTRAP_FIELDS = {"database_url", "hub_secret_key", "admin_password", "cookie_secure",
                    "data_dir", "brand_dir", "cors_origins"}

_current: Settings | None = None


def load_tolerant(overrides: dict[str, Any]) -> Settings:
    """Build settings; a bad *environment* value is dropped with a warning instead of
    preventing startup, so it can still be fixed from the Settings page."""
    overrides = dict(overrides)
    reset: set[str] = set()
    while True:
        try:
            return Settings(**overrides)
        except ValidationError as e:
            bad = {str(err["loc"][0]) for err in e.errors() if err["loc"]}
            fixable = bad - BOOTSTRAP_FIELDS - reset
            if not fixable:
                raise
            for name in fixable:
                log.warning("Ignoring invalid %s; using the default. Fix it in Settings or "
                            ".env.", name.upper())
                overrides[name] = Settings.model_fields[name].default
            reset |= fixable


def env_settings() -> Settings:
    """Settings from the environment / .env only, ignoring UI overrides."""
    return load_tolerant({})


def get_settings() -> Settings:
    global _current
    if _current is None:
        _current = load_tolerant({})
    return _current


def apply_overrides(overrides: dict[str, Any]) -> Settings:
    """Recompute the effective settings from environment defaults + stored overrides."""
    global _current
    _current = load_tolerant({k: v for k, v in overrides.items() if k not in BOOTSTRAP_FIELDS})
    return _current


def reset_settings() -> None:
    """Forget cached settings (tests)."""
    global _current
    _current = None


def validate_overrides(overrides: dict[str, Any]) -> Settings:
    """Strictly validate a candidate set of overrides; raises ValidationError."""
    return Settings(**{k: v for k, v in overrides.items() if k not in BOOTSTRAP_FIELDS})
