import secrets
import time
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import DateTime, Uuid, create_engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    MappedAsDataclass,
    mapped_column,
    sessionmaker,
)

from app.core.config import get_settings


def uuid7() -> UUID:
    """Return an RFC 9562 UUIDv7 using the current Unix time in milliseconds."""
    timestamp_ms = time.time_ns() // 1_000_000
    value = timestamp_ms << 80
    value |= 0x7 << 76
    value |= secrets.randbits(12) << 64
    value |= 0b10 << 62
    value |= secrets.randbits(62)
    return UUID(int=value)


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(MappedAsDataclass, DeclarativeBase, kw_only=True):
    pass


class UUIDPrimaryKeyMixin(MappedAsDataclass):
    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        init=False,
        default_factory=uuid7,
    )


class TimestampMixin(MappedAsDataclass):
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        init=False,
        default_factory=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        init=False,
        default_factory=utc_now,
        onupdate=utc_now,
    )


def create_session_factory(database_url: str | None = None) -> sessionmaker:
    engine = create_engine(database_url or get_settings().database_url)
    return sessionmaker(bind=engine, expire_on_commit=False)
