import logging
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    Date,
    DateTime,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, Session, SQLModel, create_engine

from app.config import BACKEND_DIR, get_settings
from app.events.schema import (
    ApprovalOut,
    ApprovalStatus,
    TaskOut,
    TaskStatus,
    utcnow,
)

log = logging.getLogger(__name__)

# JSONB on Postgres (indexable, compact), plain JSON on SQLite.
JSONType = JSON().with_variant(JSONB(), "postgresql")
TZ = DateTime(timezone=True)
# SQLite only auto-increments a column declared exactly INTEGER PRIMARY KEY.
BigId = BigInteger().with_variant(Integer(), "sqlite")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def json_col() -> Any:
    return Field(default_factory=dict, sa_column=Column(JSONType, nullable=False))


def json_list_col() -> Any:
    return Field(default_factory=list, sa_column=Column(JSONType, nullable=False))


class Task(SQLModel, table=True):
    id: str = Field(default_factory=lambda: new_id("tsk"), primary_key=True)
    title: str
    description: str = ""
    agent_id: str = Field(index=True)
    status: TaskStatus = Field(default=TaskStatus.QUEUED, index=True)
    params: dict[str, Any] = json_col()
    result: str = Field(default="", sa_type=Text)
    scheduled_for: datetime | None = Field(default=None, sa_type=TZ)
    schedule_id: str | None = Field(default=None, index=True)  # the recurring schedule, if any
    run: int = 0  # bumped each time a finished task is moved back to queued
    history: list[dict[str, Any]] = json_list_col()  # earlier runs: {run, status, result, at}
    archived_at: datetime | None = Field(default=None, sa_type=TZ, index=True)
    created_at: datetime = Field(default_factory=utcnow, sa_type=TZ)
    updated_at: datetime = Field(default_factory=utcnow, sa_type=TZ)

    def thread(self) -> str:
        """The LangGraph thread of the current run: a requeued task starts a fresh one."""
        return self.id if not self.run else f"{self.id}~r{self.run}"

    def out(self) -> TaskOut:
        return TaskOut.model_validate(self.model_dump())


class Approval(SQLModel, table=True):
    id: str = Field(default_factory=lambda: new_id("apr"), primary_key=True)
    task_id: str = Field(index=True)
    agent_id: str
    action: str
    summary: str = Field(sa_type=Text)
    details: dict[str, Any] = json_col()
    status: ApprovalStatus = Field(default=ApprovalStatus.PENDING, index=True)
    comment: str = ""
    created_at: datetime = Field(default_factory=utcnow, sa_type=TZ)
    decided_at: datetime | None = Field(default=None, sa_type=TZ)

    def out(self) -> ApprovalOut:
        return ApprovalOut.model_validate(self.model_dump())


class AuditEntry(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    ts: datetime = Field(default_factory=utcnow, sa_type=TZ, index=True)
    task_id: str | None = None
    agent_id: str | None = None
    kind: str  # e.g. task_created, approval_approved, settings_changed
    message: str = Field(sa_type=Text)
    data: dict[str, Any] = json_col()


class AppSetting(SQLModel, table=True):
    """A runtime setting override. Secret values are Fernet-encrypted in `value`."""

    key: str = Field(primary_key=True)
    value: str = Field(sa_type=Text)  # JSON-encoded; ciphertext when secret
    secret: bool = False
    updated_at: datetime = Field(default_factory=utcnow, sa_type=TZ)
    updated_by: str = "admin"


class MarketoActivity(SQLModel, table=True):
    """One Marketo activity, from Data Streams or REST polling, deduplicated per source."""

    __tablename__ = "marketo_activity"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_activity_source_external"),
        Index("ix_activity_type_time", "activity_type_id", "occurred_at"),
    )

    id: int | None = Field(default=None, sa_column=Column(BigId, primary_key=True,
                                                           autoincrement=True))
    source: str  # datastreams | rest | demo
    external_id: str
    lead_id: int | None = Field(default=None, sa_type=BigInteger, index=True)
    activity_type_id: int | None = None
    activity_type: str = ""
    occurred_at: datetime = Field(sa_type=TZ, index=True)
    primary_attribute_value: str | None = Field(default=None, sa_type=Text)
    campaign_id: int | None = None
    attributes: dict[str, Any] = json_col()
    raw: dict[str, Any] = json_col()
    ingested_at: datetime = Field(default_factory=utcnow, sa_type=TZ)


class IngestCursor(SQLModel, table=True):
    """Resume position and health for each activity source."""

    __tablename__ = "ingest_cursor"

    source: str = Field(primary_key=True)
    cursor: str = Field(default="", sa_type=Text)  # journal next-link or REST paging token
    last_poll_at: datetime | None = Field(default=None, sa_type=TZ)
    last_count: int = 0
    total_count: int = Field(default=0, sa_type=BigInteger)
    last_error: str = Field(default="", sa_type=Text)


class KpiSnapshot(SQLModel, table=True):
    """One metric for one day: agent KPIs, task/approval counts, activity volume, LLM spend."""

    __tablename__ = "kpi_snapshot"
    __table_args__ = (
        UniqueConstraint("snapshot_date", "scope", "scope_id", "metric", name="uq_kpi"),
    )

    id: int | None = Field(default=None, primary_key=True)
    snapshot_date: date = Field(sa_type=Date, index=True)
    scope: str  # agent | tasks | approvals | activities | llm | governor
    scope_id: str = ""  # agent id, activity type, model...
    metric: str
    value_num: float | None = None
    value_text: str | None = None
    created_at: datetime = Field(default_factory=utcnow, sa_type=TZ)


class AgentRun(SQLModel, table=True):
    """Final metrics of every finished task, so KPIs survive restarts and feed trends."""

    __tablename__ = "agent_run"

    id: int | None = Field(default=None, primary_key=True)
    task_id: str = Field(index=True)
    agent_id: str = Field(index=True)
    status: TaskStatus
    finished_at: datetime = Field(default_factory=utcnow, sa_type=TZ, index=True)
    metrics: dict[str, Any] = json_col()
    result: str = Field(default="", sa_type=Text)


class LlmUsage(SQLModel, table=True):
    """Every LLM attempt the router makes, including failed fallbacks."""

    __tablename__ = "llm_usage"

    id: int | None = Field(default=None, primary_key=True)
    ts: datetime = Field(default_factory=utcnow, sa_type=TZ, index=True)
    agent_id: str | None = None
    task_id: str | None = None
    tier: str
    model: str
    ok: bool
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    latency_ms: int = 0
    error: str = Field(default="", sa_type=Text)


class AgentDef(SQLModel, table=True):
    """An agent's configuration; every agent runs the tool-calling graph built from these
    fields (agents/custom.py)."""

    __tablename__ = "agent_def"

    id: str = Field(primary_key=True)  # slug, also the agent_id on tasks and events
    name: str
    title: str = ""
    color: str = "#5b6abf"
    character: str = ""  # cast model ("the-designer") or Kenney ("female-a"); "" = from the id
    # A code-defined LangGraph workflow (app/workflows) instead of the configurable agent loop.
    workflow: str = ""
    home_zone: str = "break_room"
    model_tier: str = "standard"
    enabled: bool = True
    instructions: str = Field(default="", sa_type=Text)
    tools: list[str] = json_list_col()
    skill_ids: list[str] = json_list_col()
    knowledge_ids: list[str] = json_list_col()
    memory_enabled: bool = False
    autonomy: str = "approve_writes"  # approve_writes | approve_destructive | autonomous
    max_steps: int = 12
    templates: list[dict[str, Any]] = json_list_col()
    created_at: datetime = Field(default_factory=utcnow, sa_type=TZ)
    updated_at: datetime = Field(default_factory=utcnow, sa_type=TZ)


class Skill(SQLModel, table=True):
    """A reusable playbook. Agents see each attached skill's name and description, and load
    the full body on demand with the load_skill tool."""

    id: str = Field(default_factory=lambda: new_id("skl"), primary_key=True)
    name: str = Field(unique=True)
    description: str = Field(default="", sa_type=Text)
    body: str = Field(default="", sa_type=Text)
    created_at: datetime = Field(default_factory=utcnow, sa_type=TZ)
    updated_at: datetime = Field(default_factory=utcnow, sa_type=TZ)


class KnowledgeDoc(SQLModel, table=True):
    __tablename__ = "knowledge_doc"

    id: str = Field(default_factory=lambda: new_id("kdoc"), primary_key=True)
    title: str
    source: str = ""  # file name, or empty when pasted
    content: str = Field(default="", sa_type=Text)
    embedding_model: str = ""  # model the chunks were embedded with ("" = keyword only)
    indexed_at: datetime | None = Field(default=None, sa_type=TZ)
    index_error: str = Field(default="", sa_type=Text)
    created_at: datetime = Field(default_factory=utcnow, sa_type=TZ)
    updated_at: datetime = Field(default_factory=utcnow, sa_type=TZ)


class KnowledgeChunk(SQLModel, table=True):
    __tablename__ = "knowledge_chunk"

    id: int | None = Field(default=None, sa_column=Column(BigId, primary_key=True,
                                                           autoincrement=True))
    doc_id: str = Field(index=True)
    ord: int
    content: str = Field(sa_type=Text)
    # Portable copy of the embedding. When Postgres has pgvector, knowledge.ensure_vector()
    # adds an `embedding_vec vector` column (outside this model) that search uses instead.
    embedding: list[float] | None = Field(default=None, sa_column=Column(JSONType))


_engine = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        url = settings.sqlalchemy_url
        if settings.is_postgres:
            _engine = create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=10)
        else:
            _engine = create_engine(url, connect_args={"check_same_thread": False})
    return _engine


def dispose_engine() -> None:
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


def init_db() -> None:
    """Postgres is schema-managed by Alembic; SQLite (dev/tests) is created directly."""
    if get_settings().is_postgres:
        from alembic import command
        from alembic.config import Config

        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
        command.upgrade(cfg, "head")
    else:
        SQLModel.metadata.create_all(get_engine())


def session() -> Session:
    return Session(get_engine(), expire_on_commit=False)


def audit(kind: str, message: str, *, task_id=None, agent_id=None, data=None) -> None:
    with session() as s:
        s.add(AuditEntry(kind=kind, message=message, task_id=task_id, agent_id=agent_id,
                         data=data or {}))
        s.commit()


class SceneLayout(SQLModel, table=True):
    """The Spatial view's decor: brick pieces placed in edit mode (one shared layout)."""

    __tablename__ = "scene_layout"

    id: str = Field(default="default", primary_key=True)
    pieces: list[dict[str, Any]] = json_list_col()
    version: int = 0  # bumped on every save; a save must name the version it started from
    updated_at: datetime = Field(default_factory=utcnow, sa_type=TZ)


class SceneLayoutVersion(SQLModel, table=True):
    """Earlier layouts, kept so any save can be undone (the last KEEP_VERSIONS)."""

    __tablename__ = "scene_layout_version"

    id: int | None = Field(default=None, sa_column=Column(BigId, primary_key=True,
                                                          autoincrement=True))
    version: int
    pieces: list[dict[str, Any]] = json_list_col()  # [] = the default decor
    saved_at: datetime = Field(sa_type=TZ)  # when this layout was saved
    replaced_at: datetime = Field(default_factory=utcnow, sa_type=TZ)


class WorkflowLog(SQLModel, table=True):
    """One row per item a workflow agent decided on (e.g. one lead per run)."""

    __tablename__ = "workflow_log"

    id: int | None = Field(default=None, sa_column=Column(BigId, primary_key=True,
                                                          autoincrement=True))
    workflow: str = Field(index=True)
    run_id: str = Field(index=True)  # the hub task
    thread_id: str = Field(index=True)
    item_id: str = ""  # e.g. the Marketo lead ID
    status: str = ""  # e.g. DONE, ERROR, PENDING_APPROVAL
    action: str = ""
    score: int | None = None
    tool_result: str = ""
    summary: str = Field(default="", sa_type=Text)
    data: dict[str, Any] = json_col()  # the full decision / output
    created_at: datetime = Field(default_factory=utcnow, sa_type=TZ)


class SideEffect(SQLModel, table=True):
    """Idempotency keys for external writes: an effect with a recorded key never runs twice."""

    __tablename__ = "side_effect"

    key: str = Field(primary_key=True)
    result: dict[str, Any] = json_col()
    created_at: datetime = Field(default_factory=utcnow, sa_type=TZ)


class Schedule(SQLModel, table=True):
    """A recurring task: every N minutes, daily at a time, or weekly on some days at a time,
    in the schedule's own timezone. Each occurrence becomes an ordinary task."""

    id: str = Field(default_factory=lambda: new_id("sch"), primary_key=True)
    agent_id: str = Field(index=True)
    title: str
    description: str = Field(default="", sa_type=Text)
    params: dict[str, Any] = json_col()
    kind: str = "daily"  # interval | daily | weekly
    every_minutes: int = 60  # interval
    at_time: str = "08:00"  # daily / weekly, HH:MM in tz
    weekdays: list[int] = json_list_col()  # weekly: 0 = Monday ... 6 = Sunday
    tz: str = "UTC"
    enabled: bool = True
    next_run_at: datetime | None = Field(default=None, sa_type=TZ, index=True)
    last_run_at: datetime | None = Field(default=None, sa_type=TZ)
    last_task_id: str | None = None
    last_note: str = ""  # e.g. why an occurrence was skipped
    created_at: datetime = Field(default_factory=utcnow, sa_type=TZ)
    updated_at: datetime = Field(default_factory=utcnow, sa_type=TZ)


# --- Data health scan (app/workflows/data_health) ------------------------------------------


class HealthScan(SQLModel, table=True):
    """One full-database health scan. `cursor` is where each phase got to, committed with the
    rows it covers, so a stopped scan resumes at the next unfinished batch or window."""

    __tablename__ = "health_scan"

    id: str = Field(default_factory=lambda: new_id("scan"), primary_key=True)
    task_id: str = Field(index=True)  # the task that started it
    agent_id: str = Field(index=True)
    status: str = Field(default="running", index=True)  # running | done | failed
    phase: str = "leads"  # leads | activities | values | verify | score | report | done
    params: dict[str, Any] = json_col()  # the ScanConfig it runs with
    cursor: dict[str, Any] = json_col()
    counts: dict[str, Any] = json_col()  # progress counters (leads mirrored, windows...)
    kpis: dict[str, Any] = json_col()
    report: str = Field(default="", sa_type=Text)
    error: str = Field(default="", sa_type=Text)
    started_at: datetime = Field(default_factory=utcnow, sa_type=TZ)
    updated_at: datetime = Field(default_factory=utcnow, sa_type=TZ)
    finished_at: datetime | None = Field(default=None, sa_type=TZ)


class LeadMirror(SQLModel, table=True):
    """The hub's copy of each Marketo lead (the fields a scan reads)."""

    __tablename__ = "lead_mirror"

    lead_id: int = Field(sa_column=Column(BigInteger, primary_key=True, autoincrement=False))
    data: dict[str, Any] = json_col()
    scan_id: str = Field(index=True)  # the last scan that saw it in Marketo
    synced_at: datetime = Field(default_factory=utcnow, sa_type=TZ)


class LeadActivityAgg(SQLModel, table=True):
    """Per scan and lead: engagement counts and dates from the activity history."""

    __tablename__ = "lead_activity_agg"

    scan_id: str = Field(primary_key=True)
    lead_id: int = Field(sa_column=Column(BigInteger, primary_key=True, autoincrement=False))
    opens: int = 0
    clicks: int = 0
    forms: int = 0
    visits: int = 0
    hard_bounces: int = 0
    soft_bounces: int = 0
    last_activity_at: datetime | None = Field(default=None, sa_type=TZ)
    last_engaged_at: datetime | None = Field(default=None, sa_type=TZ)  # open/click/form/visit


class LeadHealth(SQLModel, table=True):
    """Per scan and lead: a 0-100 score for each dimension, the overall score and why."""

    __tablename__ = "lead_health"
    __table_args__ = (Index("ix_lead_health_scan_overall", "scan_id", "overall"),)

    scan_id: str = Field(primary_key=True)
    lead_id: int = Field(sa_column=Column(BigInteger, primary_key=True, autoincrement=False))
    uniqueness: int = 100
    completeness: int = 0
    normalization: int = 100
    accuracy: int = 100
    contactability: int = 0
    recency: int = 0
    engagement: int = 0
    overall: int = 0
    engagement_level: str = ""  # hot | warm | cold | dormant
    dup_group: str = ""  # shared by every record of the same person
    dup_role: str = ""  # survivor | duplicate
    reach: str = ""  # usable channels: "email", "phone", "email,phone" or ""
    free_email: bool = False  # reachable only at a free email domain
    issues: list[dict[str, Any]] = json_list_col()  # [{dim, code, field?, message, fix?}]
    created_year: int | None = None
    source: str = ""  # leadSource / originalSourceType, for "where do problems come from"


class ValueMap(SQLModel, table=True):
    """Normalization mappings, e.g. country "España" -> "Spain", reused by every scan."""

    __tablename__ = "value_map"

    field: str = Field(primary_key=True)
    raw: str = Field(primary_key=True)  # lowercased, trimmed
    standard: str = ""  # "" = no standard value applies
    source: str = "rule"  # rule | llm | person
    updated_at: datetime = Field(default_factory=utcnow, sa_type=TZ)


class VerificationResult(SQLModel, table=True):
    """Paid email / phone checks (ZeroBounce, Twilio), cached so nothing is paid for twice."""

    __tablename__ = "verification_result"

    kind: str = Field(primary_key=True)  # email | phone
    value: str = Field(primary_key=True)  # normalized email / E.164 phone
    provider: str = ""
    status: str = ""  # valid | invalid | catch-all | unknown | ...
    usable: bool = False
    data: dict[str, Any] = json_col()
    checked_at: datetime = Field(default_factory=utcnow, sa_type=TZ)


class AgentReport(SQLModel, table=True):
    """What an agent reports after a run: a one-line headline and its KPI values. The profile
    panel compares the latest report with the one from a week earlier (app/reporting.py)."""

    __tablename__ = "agent_report"
    __table_args__ = (Index("ix_agent_report_agent_at", "agent_id", "at"),)

    id: int | None = Field(default=None, sa_column=Column(BigId, primary_key=True,
                                                          autoincrement=True))
    agent_id: str
    task_id: str | None = None
    at: datetime = Field(default_factory=utcnow, sa_type=TZ)
    headline: str = Field(default="", sa_type=Text)
    kpis: dict[str, Any] = json_col()  # {kpi key: number}


class DesignDeliverable(SQLModel, table=True):
    """A Designer output (landing page, email or form spec), one row per saved version.
    Feedback rounds on the same task add versions; nothing is overwritten."""

    __tablename__ = "design_deliverable"

    id: str = Field(default_factory=lambda: new_id("dsg"), primary_key=True)
    task_id: str = Field(index=True)
    agent_id: str
    kind: str  # landing_page | email | form
    name: str
    version: int = 1
    round: int = 0  # 0 = first draft, n = after the n-th feedback
    html: str = Field(default="", sa_type=Text)
    subject: str = ""
    preheader: str = ""
    spec: dict[str, Any] = json_col()  # form fields, notes
    marketo: dict[str, Any] = json_col()  # e.g. {"form_id": 1234, "snippet_id": 55}
    checks: dict[str, Any] = json_col()  # {"errors": [...], "warnings": [...]}
    created_at: datetime = Field(default_factory=utcnow, sa_type=TZ)


class TaskAttachment(SQLModel, table=True):
    """A file given to one task (or to a recurring schedule, copied into each of its runs):
    reference material for that task only, unlike agent knowledge. Deleted with the task.
    Uploaded files start unlinked (task_id and schedule_id empty) until the task is created."""

    __tablename__ = "task_attachment"

    id: str = Field(default_factory=lambda: new_id("att"), primary_key=True)
    task_id: str | None = Field(default=None, index=True)
    schedule_id: str | None = Field(default=None, index=True)
    filename: str
    mime: str = ""
    size: int = 0  # bytes uploaded
    text: str = Field(default="", sa_type=Text)  # extracted text the agent reads
    round: int = 0  # 0 = with the task; n = added with feedback round n
    created_at: datetime = Field(default_factory=utcnow, sa_type=TZ)


class MarketoChange(SQLModel, table=True):
    """Something an agent created or changed in Marketo, so people can open it there
    (links are built when shown, from Settings > Marketo address for links)."""

    __tablename__ = "marketo_change"

    id: int | None = Field(default=None, sa_column=Column(BigId, primary_key=True,
                                                          autoincrement=True))
    task_id: str | None = Field(default=None, index=True)
    agent_id: str = Field(index=True)
    kind: str  # lead | email | email_template | landing_page | landing_page_template | form
    #           | snippet | program | smart_campaign | smart_list | static_list | folder | file
    object_id: str
    name: str = ""
    action: str = ""  # created | updated | approved | deleted | requested | merged | added ...
    detail: str = Field(default="", sa_type=Text)
    created_at: datetime = Field(default_factory=utcnow, sa_type=TZ, index=True)


class TaskMessage(SQLModel, table=True):
    """The conversation on a task: what you and the agents said about it (hand-off briefs and
    replies, approvals, change requests, notes, feedback). See app/messages.py."""

    __tablename__ = "task_message"

    id: int | None = Field(default=None, sa_column=Column(BigId, primary_key=True,
                                                          autoincrement=True))
    task_id: str = Field(index=True)
    author_id: str  # an agent's id, or "you" for a person
    author_name: str = ""
    kind: str = "note"  # handoff | handed_on | your_turn | reply | approved | changes
    #                     | rejected | feedback | note | result
    text: str = Field(sa_type=Text)
    created_at: datetime = Field(default_factory=utcnow, sa_type=TZ, index=True)
