"""The single event contract shared by backend and frontend.

Frontend types are generated from this module (see export_schema.py); edit here, then run
`npm run gen:types` in frontend/.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel


def utcnow() -> datetime:
    return datetime.now(UTC)


class Zone(StrEnum):
    DATABASE = "database"
    CAMPAIGNS = "campaigns"
    DESIGN_STUDIO = "design_studio"
    BREAK_ROOM = "break_room"


class AgentState(StrEnum):
    IDLE = "IDLE"
    TRAVELING = "TRAVELING"
    BUSY = "BUSY"
    NEEDS_HELP = "NEEDS_HELP"
    ERROR = "ERROR"


class TaskStatus(StrEnum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    NEEDS_APPROVAL = "needs_approval"
    DONE = "done"
    FAILED = "failed"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


MetricValue = str | int | float


class Contract(BaseModel):
    # Fields with defaults are always serialized, so mark them required in the exported schema.
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class Handoff(Contract):
    """One agent handing work to another: the two meet and exchange these lines."""
    to_agent_id: str
    task_id: str  # the task created for the receiver
    line_from: str
    line_to: str


class AgentEvent(Contract):
    type: Literal["agent_event"] = "agent_event"
    agent_id: str
    task_id: str | None = None
    action: str
    source_zone: Zone
    target_zone: Zone
    status_text: str
    state: AgentState
    metrics: dict[str, MetricValue] = Field(default_factory=dict)
    handoff: Handoff | None = None  # action "handoff": who the agent is handing work to
    ts: datetime = Field(default_factory=utcnow)


class TaskTemplate(Contract):
    title: str
    description: str = ""
    params: dict[str, Any] = Field(default_factory=dict)


class AgentProfile(Contract):
    id: str
    name: str
    title: str
    home_zone: Zone
    model_tier: Literal["fast", "standard", "strong"]
    channels: list[Literal["rest", "mcp"]]
    color: str
    character: str = ""  # Mini Characters model; "" = picked from the id
    workflow: str = ""  # a code-defined workflow (app/workflows); "" = configurable agent
    knowledge: list[str]  # titles of attached knowledge documents
    templates: list[TaskTemplate]
    enabled: bool = True
    tools: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)  # skill names
    memory_enabled: bool = False
    autonomy: Literal["approve_writes", "approve_destructive", "autonomous"] = "approve_writes"


class AgentStatus(Contract):
    agent_id: str
    zone: Zone
    state: AgentState
    status_text: str
    task_id: str | None = None
    metrics: dict[str, MetricValue] = Field(default_factory=dict)


class TaskOut(Contract):
    id: str
    title: str
    description: str
    agent_id: str
    status: TaskStatus
    params: dict[str, Any]
    result: str
    scheduled_for: datetime | None
    schedule_id: str | None = None
    run: int = 0
    history: list[dict[str, Any]] = Field(default_factory=list)
    archived_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ApprovalOut(Contract):
    id: str
    task_id: str
    agent_id: str
    action: str
    summary: str
    details: dict[str, Any]
    status: ApprovalStatus
    comment: str
    created_at: datetime
    decided_at: datetime | None


class GovernorStats(Contract):
    calls_in_window: int
    window_limit: int
    window_s: float
    in_flight: int
    max_concurrent: int
    queued: int
    daily_used: int
    daily_quota: int
    by_channel: dict[str, int]


# --- Server -> client WebSocket messages -------------------------------------------------


class SnapshotMsg(Contract):
    type: Literal["snapshot"] = "snapshot"
    agents: list[AgentProfile]
    statuses: list[AgentStatus]
    tasks: list[TaskOut]
    approvals: list[ApprovalOut]
    governor: GovernorStats
    marketo_mode: Literal["demo", "live"]


class TaskUpdatedMsg(Contract):
    type: Literal["task_updated"] = "task_updated"
    task: TaskOut


class TaskDeletedMsg(Contract):
    type: Literal["task_deleted"] = "task_deleted"
    task_id: str


class ApprovalUpdatedMsg(Contract):
    type: Literal["approval_updated"] = "approval_updated"
    approval: ApprovalOut


class GovernorMsg(Contract):
    type: Literal["governor"] = "governor"
    stats: GovernorStats


class ServerMessage(
    RootModel[
        Annotated[
            SnapshotMsg
            | AgentEvent
            | TaskUpdatedMsg
            | TaskDeletedMsg
            | ApprovalUpdatedMsg
            | GovernorMsg,
            Field(discriminator="type"),
        ]
    ]
):
    pass
