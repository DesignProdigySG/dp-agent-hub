"""Runtime settings editable from the UI, persisted in the database.

Secret values are encrypted with the master key before they touch the database and are never
returned to the browser: the API reports only whether a secret is set and its last 4
characters.
"""

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import ValidationError
from sqlmodel import select

from app.config import (
    Settings,
    apply_overrides,
    env_settings,
    get_settings,
    load_tolerant,
    validate_overrides,
)
from app.db import AppSetting, audit, session
from app.events.schema import utcnow
from app.security import ADMIN_HASH_KEY, decrypt, encrypt

log = logging.getLogger(__name__)

Kind = Literal["text", "secret", "number", "bool", "select", "url"]


@dataclass(frozen=True)
class FieldSpec:
    key: str
    group: str
    label: str
    kind: Kind = "text"
    help: str = ""
    options: list[str] = field(default_factory=list)
    placeholder: str = ""

    @property
    def secret(self) -> bool:
        return self.kind == "secret"


GROUPS: list[tuple[str, str, str]] = [
    ("access", "Access", "Who can see the hub."),
    ("marketo", "Marketo", "LaunchPoint credentials shared by the REST/Bulk API and MCP."),
    ("llm", "LLM router", "Claude by default; any LiteLLM provider can be routed to."),
    ("knowledge", "Knowledge search",
     "Embeddings for semantic search over agent knowledge. Empty uses keyword search."),
    ("activities", "Activity ingestion",
     "Marketo Data Streams (Adobe I/O Events journal) with REST polling as a fallback."),
    ("datalake", "Azure Data Lake", "Archive raw activity events and daily snapshots."),
    ("notifications", "Approval notifications",
     "Tell reviewers when an agent needs approval, with one-tap Approve / Reject links."),
    ("websearch", "Web search",
     "Lets agents search the web (Brave Search) to research companies and prospects."),
    ("verification", "Email & phone verification",
     "Paid checks the Data Doctor runs when its ZeroBounce / Twilio skills are attached. "
     "Results are cached, so a value is never paid for twice."),
    ("email", "Email", "Send approval requests by email through any SMTP server."),
    ("governor", "Rate governor", "Shared Marketo API budget for REST and MCP."),
    ("operations", "Operations", ""),
]

FIELDS: list[FieldSpec] = [
    FieldSpec("public_read_access", "access", "Let signed-out viewers see the board", "bool",
              "Settings, approvals and edits always need the admin password."),
    FieldSpec("marketo_mode", "marketo", "Mode", "select",
              "Demo uses an in-memory sandbox; live calls your Marketo instance.",
              ["demo", "live"]),
    FieldSpec("marketo_munchkin_id", "marketo", "Munchkin ID", placeholder="123-ABC-456",
              help="Admin > Integration > Munchkin. The REST URL is built from it."),
    FieldSpec("marketo_client_id", "marketo", "Client ID"),
    FieldSpec("marketo_client_secret", "marketo", "Client secret", "secret"),
    FieldSpec("marketo_mcp_url", "marketo", "MCP server URL", "url"),
    FieldSpec("marketo_ui_url", "marketo", "Marketo address for links",
              help="So agents can link to what they create or change. Open any program in "
                   "Marketo and copy its address up to (not including) the code that starts "
                   "with ME or PG, e.g. https://experience.adobe.com/#/@yourorg/so:123-ABC-456/"
                   "marketo-engage/ or https://app-ab12.marketo.com/#",
              placeholder="https://app-ab12.marketo.com/#"),
    FieldSpec("llm_routing", "llm", "Routing", "select",
              "Auto escalates large or high-stakes prompts and steps down near the budget; "
              "fixed always uses each agent's tier.", ["auto", "fixed"]),
    FieldSpec("llm_fast_model", "llm", "Fast tier model",
              help="provider/model, e.g. anthropic/claude-haiku-5-5, openai/gpt-5-mini, "
                   "ollama/qwen2.5:14b"),
    FieldSpec("llm_standard_model", "llm", "Standard tier model"),
    FieldSpec("llm_strong_model", "llm", "Strong tier model"),
    FieldSpec("llm_fallback_models", "llm", "Fallback models",
              help="Comma-separated; tried in order if the tier's model fails."),
    FieldSpec("llm_daily_budget_usd", "llm", "Daily budget (USD)", "number",
              "0 = no cap. Auto routing steps down a tier at 80%; calls stop at 100%."),
    FieldSpec("anthropic_api_key", "llm", "Anthropic API key", "secret"),
    FieldSpec("openai_api_key", "llm", "OpenAI API key", "secret"),
    FieldSpec("gemini_api_key", "llm", "Gemini API key", "secret"),
    FieldSpec("azure_openai_api_key", "llm", "Azure OpenAI API key", "secret"),
    FieldSpec("azure_openai_endpoint", "llm", "Azure OpenAI endpoint", "url"),
    FieldSpec("ollama_base_url", "llm", "Ollama base URL", "url"),
    FieldSpec("embedding_model", "knowledge", "Embedding model",
              help="provider/model via LiteLLM, e.g. voyage/voyage-3.5, "
                   "openai/text-embedding-3-small, ollama/nomic-embed-text. Changing it "
                   "re-indexes every document."),
    FieldSpec("voyage_api_key", "knowledge", "Voyage API key", "secret",
              "OpenAI, Gemini, Azure and Ollama embeddings reuse the LLM router's keys."),
    FieldSpec("activity_source", "activities", "Source", "select",
              "Auto uses Data Streams when configured, else REST polling in live mode, else "
              "demo data.", ["auto", "datastreams", "rest", "off"]),
    FieldSpec("activity_poll_seconds", "activities", "Poll interval (seconds)", "number"),
    FieldSpec("activity_retention_days", "activities", "Keep activities (days)", "number"),
    FieldSpec("rest_activity_type_ids", "activities", "REST activity type IDs",
              help="Comma-separated, max 10 (REST fallback only)."),
    FieldSpec("adobe_org_id", "activities", "Adobe IMS org ID", placeholder="...@AdobeOrg"),
    FieldSpec("adobe_client_id", "activities", "Adobe client ID (API key)"),
    FieldSpec("adobe_client_secret", "activities", "Adobe client secret", "secret"),
    FieldSpec("adobe_ims_scopes", "activities", "IMS scopes"),
    FieldSpec("datastreams_journal_url", "activities", "Journal URL", "url",
              "From the event registration in Adobe Developer Console."),
    FieldSpec("adls_enabled", "datalake", "Archive to Data Lake", "bool"),
    FieldSpec("adls_auth", "datalake", "Authentication", "select",
              options=["connection_string", "service_principal"]),
    FieldSpec("adls_connection_string", "datalake", "Connection string", "secret"),
    FieldSpec("adls_account_url", "datalake", "Account URL", "url",
              placeholder="https://<account>.dfs.core.windows.net"),
    FieldSpec("adls_filesystem", "datalake", "Filesystem (container)"),
    FieldSpec("adls_path_prefix", "datalake", "Path prefix"),
    FieldSpec("azure_tenant_id", "datalake", "Tenant ID"),
    FieldSpec("azure_client_id", "datalake", "Service principal client ID"),
    FieldSpec("azure_client_secret", "datalake", "Service principal secret", "secret"),
    FieldSpec("hub_public_url", "notifications", "Hub address for links", "url",
              "Approve / Reject / Review links point here. They only open where this address "
              "is reachable: this machine or network while the hub runs locally.",
              placeholder="http://localhost:5180"),
    FieldSpec("approval_link_hours", "notifications", "Links expire after (hours)", "number",
              "A link also stops working once the request is decided."),
    FieldSpec("notify_task_failures", "notifications", "Also notify when a task fails", "bool"),
    FieldSpec("email_enabled", "email", "Send email", "bool"),
    FieldSpec("email_to", "email", "Reviewers", help="Comma-separated email addresses.",
              placeholder="ops@example.com, lead@example.com"),
    FieldSpec("email_from", "email", "From address", placeholder="agent-hub@example.com"),
    FieldSpec("smtp_host", "email", "SMTP server", placeholder="smtp.office365.com"),
    FieldSpec("smtp_port", "email", "Port", "number", "587 for STARTTLS, 465 for SSL."),
    FieldSpec("smtp_security", "email", "Security", "select", options=["starttls", "ssl", "none"]),
    FieldSpec("smtp_username", "email", "Username"),
    FieldSpec("smtp_password", "email", "Password / app password", "secret"),
    FieldSpec("brave_api_key", "websearch", "Brave Search API key", "secret",
              "brave.com/search/api. Used by the web_search tool."),
    FieldSpec("zerobounce_api_key", "verification", "ZeroBounce API key", "secret",
              "zerobounce.net > API. About USD 0.008 per email; only emails that pass the free "
              "checks are sent."),
    FieldSpec("twilio_account_sid", "verification", "Twilio Account SID"),
    FieldSpec("twilio_auth_token", "verification", "Twilio auth token", "secret",
              "Twilio Lookup v2 number validation (free tier); only well-formed numbers are "
              "sent."),
    FieldSpec("verify_max_per_scan", "verification", "Max paid checks per scan", "number",
              "Each for emails and phones. The rest are left as \"not verified\"."),
    FieldSpec("governor_calls", "governor", "Calls per window", "number"),
    FieldSpec("governor_window_s", "governor", "Window (seconds)", "number"),
    FieldSpec("governor_max_concurrent", "governor", "Max concurrent calls", "number"),
    FieldSpec("governor_daily_quota", "governor", "Daily quota", "number"),
    FieldSpec("agent_pacing_s", "operations", "Agent pacing (seconds per step)", "number"),
    FieldSpec("snapshot_hour_utc", "operations", "Daily snapshot hour (UTC)", "number"),
]
FIELD_BY_KEY = {f.key: f for f in FIELDS}

Listener = Callable[[Settings, set[str]], Awaitable[None]]


class SettingsError(ValueError):
    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))


class SettingsStore:
    def __init__(self) -> None:
        self._overrides: dict[str, Any] = {}
        self._admin_hash: str | None = None
        self._listeners: list[Listener] = []

    # --- load / apply -----------------------------------------------------------------------

    def load(self) -> Settings:
        with session() as s:
            rows = s.exec(select(AppSetting)).all()
        self._overrides = {}
        for row in rows:
            if row.key == ADMIN_HASH_KEY:
                self._admin_hash = row.value
            elif row.key in FIELD_BY_KEY:
                raw = decrypt(row.value) if row.secret else row.value
                self._overrides[row.key] = json.loads(raw)
        return apply_overrides(self._overrides)

    def on_change(self, listener: Listener) -> None:
        self._listeners.append(listener)

    # --- admin password ---------------------------------------------------------------------

    def admin_hash(self) -> str | None:
        return self._admin_hash

    def set_admin_hash(self, value: str) -> None:
        with session() as s:
            row = s.get(AppSetting, ADMIN_HASH_KEY) or AppSetting(key=ADMIN_HASH_KEY, value="")
            row.value, row.updated_at = value, utcnow()
            s.add(row)
            s.commit()
        self._admin_hash = value

    # --- view -------------------------------------------------------------------------------

    def describe(self) -> dict[str, Any]:
        effective = get_settings()
        env_only = env_settings()
        fields = []
        for f in FIELDS:
            value = getattr(effective, f.key)
            default = Settings.model_fields[f.key].default
            source = ("ui" if f.key in self._overrides
                      else "env" if getattr(env_only, f.key) != default else "default")
            item: dict[str, Any] = {
                "key": f.key, "group": f.group, "label": f.label, "kind": f.kind,
                "help": f.help, "options": f.options, "placeholder": f.placeholder,
                "source": source,
            }
            if f.secret:
                item["is_set"] = bool(value)
                item["hint"] = f"…{value[-4:]}" if len(value) >= 12 else ""
                item["value"] = None
            else:
                item["value"] = value
            fields.append(item)
        groups = [{"id": g, "label": label, "description": d} for g, label, d in GROUPS]
        return {"groups": groups, "fields": fields}

    # --- update -----------------------------------------------------------------------------

    async def update(self, changes: dict[str, Any], actor: str = "admin") -> set[str]:
        """Apply changes. A value of None removes the UI override (back to env/default)."""
        unknown = set(changes) - set(FIELD_BY_KEY)
        if unknown:
            raise SettingsError({k: "unknown setting" for k in unknown})
        candidate = dict(self._overrides)
        # Pasted IDs, keys and URLs often carry stray whitespace; it breaks HTTP headers.
        changes = {k: v.strip() if isinstance(v, str) else v for k, v in changes.items()}
        for key, value in changes.items():
            if value is None:
                candidate.pop(key, None)
            else:
                candidate[key] = value
        try:
            validated = validate_overrides(candidate)
        except ValidationError as e:
            errors = {str(err["loc"][0]) if err["loc"] else "_":
                      err["msg"].removeprefix("Value error, ") for err in e.errors()}
            mine = {k: v for k, v in errors.items() if k in changes}
            if mine:
                raise SettingsError(mine) from None
            # Only pre-existing bad values (e.g. from .env) failed; don't block this edit.
            validated = load_tolerant(candidate)

        with session() as s:
            for key, value in changes.items():
                row = s.get(AppSetting, key)
                if value is None:
                    if row:
                        s.delete(row)
                    continue
                spec = FIELD_BY_KEY[key]
                encoded = json.dumps(getattr(validated, key), default=str)
                row = row or AppSetting(key=key, value="")
                row.value = encrypt(encoded) if spec.secret else encoded
                row.secret, row.updated_at, row.updated_by = spec.secret, utcnow(), actor
                s.add(row)
            s.commit()

        self._overrides = {k: getattr(validated, k) for k in candidate}
        settings = apply_overrides(self._overrides)
        changed = set(changes)
        audit("settings_changed", ", ".join(sorted(changed)), data={"keys": sorted(changed)})
        for listener in self._listeners:
            try:
                await listener(settings, changed)
            except Exception:
                log.exception("settings listener failed")
        return changed


_store: SettingsStore | None = None


def get_store() -> SettingsStore:
    global _store
    if _store is None:
        _store = SettingsStore()
    return _store


def reset_store() -> None:
    global _store
    _store = None
