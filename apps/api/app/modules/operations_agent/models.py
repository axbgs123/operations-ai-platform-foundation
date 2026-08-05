from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import (
    Base,
    TimestampMixin,
    UTCDateTime,
    UUIDPrimaryKeyMixin,
    utc_now,
)
from app.modules.content.account_models import Platform, platform_type


class AgentRunStatus(StrEnum):
    DRAFT = "draft"
    AWAITING_PLAN_APPROVAL = "awaiting_plan_approval"
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_ACTION_CONFIRMATION = "awaiting_action_confirmation"
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    FAILED = "failed"
    CONFIGURATION_REQUIRED = "configuration_required"
    COMPENSATION_REQUIRED = "compensation_required"
    PROVIDER_OUTCOME_UNKNOWN = "provider_outcome_unknown"


class AgentStepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_ACTION_CONFIRMATION = "awaiting_action_confirmation"
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    FAILED = "failed"
    COMPENSATION_REQUIRED = "compensation_required"
    PROVIDER_OUTCOME_UNKNOWN = "provider_outcome_unknown"


class AgentConfirmationStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"


class AgentPlanStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
    INVALIDATED = "invalidated"


class AgentToolRisk(StrEnum):
    READ_ONLY = "read_only"
    DRAFT_WRITE = "draft_write"
    PROTECTED_WRITE = "protected_write"


class AgentArtifactKind(StrEnum):
    ANALYSIS = "analysis"
    DRAFT = "draft"
    TEXT_DRAFT = "text_draft"
    COVER_RECOMMENDATION = "cover_recommendation"
    RISK_SCAN = "risk_scan"
    EXECUTION_SUMMARY = "execution_summary"
    EXPORT = "export"


def _enum_type(enum: type[StrEnum], name: str) -> Enum:
    return Enum(
        enum,
        name=name,
        native_enum=False,
        values_callable=lambda members: [member.value for member in members],
    )


agent_run_status_type = _enum_type(AgentRunStatus, "agent_run_status")
agent_step_status_type = _enum_type(AgentStepStatus, "agent_step_status")
agent_confirmation_status_type = _enum_type(
    AgentConfirmationStatus,
    "agent_confirmation_status",
)
agent_plan_status_type = _enum_type(AgentPlanStatus, "agent_plan_status")
agent_tool_risk_type = _enum_type(AgentToolRisk, "agent_tool_risk")
agent_artifact_kind_type = _enum_type(
    AgentArtifactKind,
    "agent_artifact_kind",
)


class AgentBriefing(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_briefings"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "input_fingerprint",
            "algorithm_version",
            name="uq_agent_briefings_workspace_input_algorithm",
        ),
        Index(
            "ix_agent_briefings_workspace_created",
            "workspace_id",
            "created_at",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )
    input_fingerprint: Mapped[str] = mapped_column(String(64))
    algorithm_version: Mapped[str] = mapped_column(String(80))
    tool_catalog_version: Mapped[str] = mapped_column(String(80))
    candidates: Mapped[list[dict[str, object]]] = mapped_column(JSON)
    priority_candidate: Mapped[dict[str, object] | None] = mapped_column(
        JSON,
        default=None,
    )
    data_cutoff_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        default_factory=utc_now,
    )


class AgentPlan(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_plans"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_agent_plans_workspace_idempotency",
        ),
        CheckConstraint(
            "platform IN ('douyin', 'xiaohongshu')",
            name="ck_agent_plans_platform",
        ),
        Index("ix_agent_plans_workspace_created", "workspace_id", "created_at"),
        Index("ix_agent_plans_account", "account_id", "created_at"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )
    briefing_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agent_briefings.id", ondelete="RESTRICT"),
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("platform_accounts.id", ondelete="RESTRICT"),
    )
    platform: Mapped[Platform] = mapped_column(platform_type)
    idempotency_key: Mapped[str] = mapped_column(String(200))
    input_fingerprint: Mapped[str] = mapped_column(String(64))
    tool_catalog_version: Mapped[str] = mapped_column(String(80))
    document: Mapped[dict[str, object]] = mapped_column(JSON)
    plan_fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[AgentPlanStatus] = mapped_column(
        agent_plan_status_type,
        default=AgentPlanStatus.DRAFT,
    )
    created_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspace_members.id", ondelete="SET NULL"),
        default=None,
    )
    approved_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspace_members.id", ondelete="SET NULL"),
        default=None,
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        default=None,
    )


class AgentRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "plan_id",
            name="uq_agent_runs_workspace_plan",
        ),
        CheckConstraint(
            "platform IN ('douyin', 'xiaohongshu')",
            name="ck_agent_runs_platform",
        ),
        CheckConstraint(
            "operation_version >= 1",
            name="ck_agent_runs_operation_version",
        ),
        CheckConstraint(
            "current_step_index >= 0",
            name="ck_agent_runs_current_step_index",
        ),
        Index("ix_agent_runs_workspace_status", "workspace_id", "status"),
        Index("ix_agent_runs_account_created", "account_id", "created_at"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )
    plan_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agent_plans.id", ondelete="RESTRICT"),
    )
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("platform_accounts.id", ondelete="RESTRICT"),
    )
    platform: Mapped[Platform] = mapped_column(platform_type)
    status: Mapped[AgentRunStatus] = mapped_column(
        agent_run_status_type,
        default=AgentRunStatus.DRAFT,
    )
    current_step_index: Mapped[int] = mapped_column(Integer, default=0)
    operation_version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspace_members.id", ondelete="SET NULL"),
        default=None,
    )
    claim_token: Mapped[str | None] = mapped_column(String(120), default=None)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        default=None,
    )
    safe_error_code: Mapped[str | None] = mapped_column(
        String(80),
        default=None,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        default=None,
    )

    __mapper_args__ = {"version_id_col": operation_version}


class AgentRunStep(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_run_steps"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "step_index",
            name="uq_agent_steps_run_index",
        ),
        CheckConstraint(
            "step_index >= 0",
            name="ck_agent_steps_step_index",
        ),
        CheckConstraint(
            "operation_version >= 1",
            name="ck_agent_steps_operation_version",
        ),
        Index("ix_agent_steps_workspace_run", "workspace_id", "run_id"),
        Index("ix_agent_steps_run_status", "run_id", "status"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )
    run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
    )
    step_index: Mapped[int] = mapped_column(Integer)
    tool_name: Mapped[str] = mapped_column(String(80))
    tool_version: Mapped[str] = mapped_column(String(40))
    tool_risk: Mapped[AgentToolRisk] = mapped_column(agent_tool_risk_type)
    input_fingerprint: Mapped[str] = mapped_column(String(64))
    input_envelope: Mapped[dict[str, object]] = mapped_column(JSON)
    status: Mapped[AgentStepStatus] = mapped_column(
        agent_step_status_type,
        default=AgentStepStatus.PENDING,
    )
    operation_version: Mapped[int] = mapped_column(Integer, default=1)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    result_envelope: Mapped[dict[str, object] | None] = mapped_column(
        JSON,
        default=None,
    )
    safe_error_code: Mapped[str | None] = mapped_column(
        String(80),
        default=None,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        default=None,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        default=None,
    )

    __mapper_args__ = {"version_id_col": operation_version}


class AgentConfirmation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_confirmations"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "step_id",
            "action_fingerprint",
            name="uq_agent_confirmations_run_step_action",
        ),
        Index(
            "ix_agent_confirmations_workspace_status",
            "workspace_id",
            "status",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )
    run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
    )
    step_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agent_run_steps.id", ondelete="CASCADE"),
    )
    action_fingerprint: Mapped[str] = mapped_column(String(64))
    action_summary: Mapped[dict[str, object]] = mapped_column(JSON)
    status: Mapped[AgentConfirmationStatus] = mapped_column(
        agent_confirmation_status_type,
        default=AgentConfirmationStatus.PENDING,
    )
    requested_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspace_members.id", ondelete="SET NULL"),
        default=None,
    )
    resolved_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspace_members.id", ondelete="SET NULL"),
        default=None,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        default=None,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        default=None,
    )


class AgentArtifact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_artifacts"
    __table_args__ = (
        Index("ix_agent_artifacts_workspace_run", "workspace_id", "run_id"),
        Index("ix_agent_artifacts_resource", "resource_type", "resource_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )
    run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
    )
    kind: Mapped[AgentArtifactKind] = mapped_column(agent_artifact_kind_type)
    resource_type: Mapped[str] = mapped_column(String(80))
    resource_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    step_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agent_run_steps.id", ondelete="SET NULL"),
        default=None,
    )
    safe_metadata: Mapped[dict[str, object]] = mapped_column(
        JSON,
        default_factory=dict,
    )


class AgentEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "agent_events"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_agent_events_workspace_idempotency",
        ),
        Index("ix_agent_events_workspace_created", "workspace_id", "created_at"),
        Index("ix_agent_events_run_created", "run_id", "created_at"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )
    event_type: Mapped[str] = mapped_column(String(80))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    safe_payload: Mapped[dict[str, object]] = mapped_column(JSON)
    run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        default=None,
    )
    step_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agent_run_steps.id", ondelete="CASCADE"),
        default=None,
    )
    actor_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspace_members.id", ondelete="SET NULL"),
        default=None,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        init=False,
        default_factory=utc_now,
    )
