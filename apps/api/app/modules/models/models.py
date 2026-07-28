from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ModelConfigStatus(StrEnum):
    VERIFIED = "verified"
    EXPERIMENTAL = "experimental"
    COMMUNITY = "community"
    INCOMPATIBLE = "incompatible"


model_config_status_type = Enum(
    ModelConfigStatus,
    name="model_config_status",
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
)


class ModelConfig(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "model_configs"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "provider",
            "model_id",
            name="uq_model_config_workspace_provider_model",
        ),
        CheckConstraint(
            "provider <> 'qianwen' OR "
            "(region IS NOT NULL AND provider_workspace_id IS NOT NULL)",
            name="ck_model_configs_qianwen_endpoint_fields",
        ),
        Index("ix_model_configs_workspace_id", "workspace_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )
    provider: Mapped[str] = mapped_column(String(80))
    model_id: Mapped[str] = mapped_column(String(160))
    capabilities: Mapped[list[str]] = mapped_column(JSON)
    status: Mapped[ModelConfigStatus] = mapped_column(model_config_status_type)
    encrypted_api_key: Mapped[str] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        default=None,
    )
    provider_workspace_id: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
        default=None,
    )
    encryption_key_version: Mapped[str] = mapped_column(String(20), default="v1")
