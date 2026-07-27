from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
import hashlib
import json
from typing import Literal, cast
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import WorkspaceContext
from app.modules.analysis.models import (
    AnalysisRun,
    AnalysisSuggestion,
    ProductEvent,
    ProductEventOutbox,
)
from app.modules.content.account_models import Platform, PlatformAccount
from app.modules.content.models import Content
from app.modules.generation.models import TextGenerationRun


EVENT_VERSION = 1
ProviderMode = Literal["real", "mock"]
PropertyValue = StrictBool | StrictInt | StrictFloat | StrictStr


class EventName(StrEnum):
    ANALYSIS_STARTED = "analysis.started"
    ANALYSIS_PROCESSING_STARTED = "analysis.processing_started"
    ANALYSIS_COMPLETED = "analysis.completed"
    ANALYSIS_VIEWED = "analysis.viewed"
    ANALYSIS_FEEDBACK = "analysis.feedback"
    COLLECTION_STARTED = "collection.started"
    COLLECTION_CONFIRMED = "collection.confirmed"
    SUGGESTION_SAVED = "suggestion.saved"
    SUGGESTION_ADOPTED = "suggestion.adopted"
    SUGGESTION_REJECTED = "suggestion.rejected"
    GENERATION_COMPLETED = "generation.completed"
    GENERATION_ADOPTED = "generation.adopted"
    GENERATION_EDITED = "generation.edited"
    GENERATION_REJECTED = "generation.rejected"
    DRAFT_CREATED = "draft.created"
    CONTENT_PUBLISHED = "content.published"
    COMPLETENESS_CHANGED = "completeness.changed"
    EFFECTIVE_LOOP_COMPLETED = "effective_loop.completed"


class EventIdempotencyConflict(ValueError):
    pass


class EventPayloadRejected(ValueError):
    pass


class ProductEventInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_name: EventName
    idempotency_key: str = Field(
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    account_id: UUID | None = None
    content_id: UUID | None = None
    analysis_run_id: UUID | None = None
    generation_run_id: UUID | None = None
    suggestion_id: UUID | None = None
    properties: dict[str, PropertyValue] = Field(default_factory=dict)
    provider_mode: ProviderMode = "real"


_SOURCES: set[object] = {
    "manual",
    "csv",
    "xlsx",
    "screenshot",
    "extension",
}
_PROPERTY_RULES: dict[EventName, dict[str, set[object] | None]] = {
    EventName.COLLECTION_STARTED: {"source": _SOURCES},
    EventName.COLLECTION_CONFIRMED: {"source": _SOURCES},
    EventName.ANALYSIS_STARTED: {
        "trigger_kind": {"manual", "auto"},
    },
    EventName.ANALYSIS_PROCESSING_STARTED: {},
    EventName.ANALYSIS_COMPLETED: {
        "status": {"succeeded"},
        "queue_ms": None,
        "processing_ms": None,
    },
    EventName.ANALYSIS_VIEWED: {"analysis_version": None},
    EventName.ANALYSIS_FEEDBACK: {
        "rating": {"useful", "not_useful"},
        "analysis_version": None,
    },
    EventName.SUGGESTION_SAVED: {"suggestion_version": None},
    EventName.SUGGESTION_ADOPTED: {"suggestion_version": None},
    EventName.SUGGESTION_REJECTED: {"suggestion_version": None},
    EventName.GENERATION_COMPLETED: {"generation_version": None},
    EventName.GENERATION_ADOPTED: {
        "modification_magnitude": None,
        "algorithm_version": None,
    },
    EventName.GENERATION_EDITED: {
        "modification_magnitude": None,
        "algorithm_version": None,
    },
    EventName.GENERATION_REJECTED: {"reason_code": None},
    EventName.DRAFT_CREATED: {"generation_version": None},
    EventName.CONTENT_PUBLISHED: {"content_version": None},
    EventName.COMPLETENESS_CHANGED: {
        "score": None,
        "completeness_version": None,
    },
    EventName.EFFECTIVE_LOOP_COMPLETED: {
        "metric_version": None,
        "iso_week": None,
    },
}
_REQUIRED_PROPERTIES: dict[EventName, set[str]] = {
    EventName.COLLECTION_STARTED: {"source"},
    EventName.COLLECTION_CONFIRMED: {"source"},
    EventName.ANALYSIS_STARTED: {"trigger_kind"},
    EventName.ANALYSIS_FEEDBACK: {"rating", "analysis_version"},
    EventName.GENERATION_ADOPTED: {
        "modification_magnitude",
        "algorithm_version",
    },
    EventName.GENERATION_EDITED: {
        "modification_magnitude",
        "algorithm_version",
    },
    EventName.COMPLETENESS_CHANGED: {
        "score",
        "completeness_version",
    },
    EventName.EFFECTIVE_LOOP_COMPLETED: {"metric_version", "iso_week"},
}


def _validate_properties(event: ProductEventInput) -> None:
    rules = _PROPERTY_RULES[event.event_name]
    keys = set(event.properties)
    if not _REQUIRED_PROPERTIES.get(event.event_name, set()) <= keys:
        raise EventPayloadRejected("required event properties are missing")
    if not keys <= set(rules):
        raise EventPayloadRejected("event properties are not allowed")
    for key, value in event.properties.items():
        if isinstance(value, str) and len(value) > 80:
            raise EventPayloadRejected("event property is too long")
        allowed = rules[key]
        if allowed is not None and value not in allowed:
            raise EventPayloadRejected("event property value is invalid")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if value < 0 or value > 100_000_000:
                raise EventPayloadRejected("event numeric property is out of range")


def _fingerprint(event: ProductEventInput) -> str:
    payload = event.model_dump(mode="json")
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _publish(
    session: Session,
    outbox: ProductEventOutbox,
    occurred_at: datetime,
) -> ProductEvent:
    payload = outbox.payload
    event = ProductEvent(
        workspace_id=outbox.workspace_id,
        event_name=str(payload["event_name"]),
        event_version=int(str(payload["event_version"])),
        entity_type=str(payload["entity_type"]),
        entity_id=UUID(str(payload["entity_id"])),
        server_occurred_at=occurred_at,
        actor_id=(
            UUID(str(payload["actor_id"]))
            if payload.get("actor_id") is not None
            else None
        ),
        platform=(
            Platform(str(payload["platform"]))
            if payload.get("platform") is not None
            else None
        ),
        account_id=(
            UUID(str(payload["account_id"]))
            if payload.get("account_id") is not None
            else None
        ),
        content_id=(
            UUID(str(payload["content_id"]))
            if payload.get("content_id") is not None
            else None
        ),
        analysis_run_id=(
            UUID(str(payload["analysis_run_id"]))
            if payload.get("analysis_run_id") is not None
            else None
        ),
        generation_run_id=(
            UUID(str(payload["generation_run_id"]))
            if payload.get("generation_run_id") is not None
            else None
        ),
        suggestion_id=(
            UUID(str(payload["suggestion_id"]))
            if payload.get("suggestion_id") is not None
            else None
        ),
        idempotency_key=outbox.idempotency_key,
        payload_fingerprint=outbox.payload_fingerprint,
        provider_mode=str(payload["provider_mode"]),
        analytics_eligible=bool(payload["analytics_eligible"]),
        properties=cast(dict[str, object], payload["properties"]),
    )
    session.add(event)
    session.flush()
    outbox.processed_at = occurred_at
    outbox.event_id = event.id
    outbox.error_code = None
    session.flush()
    return event


Publisher = Callable[[Session, ProductEventOutbox, datetime], ProductEvent]


class EventService:
    def __init__(
        self,
        session: Session,
        context: WorkspaceContext,
        *,
        now: Callable[[], datetime] | None = None,
        publisher: Publisher | None = None,
    ) -> None:
        self._session = session
        self._context = context
        self._now = now or (lambda: datetime.now(UTC))
        self._publisher = publisher or _publish

    def _resolve_account(self, event: ProductEventInput) -> PlatformAccount:
        account_id = event.account_id
        if event.content_id is not None:
            content = self._session.scalar(
                select(Content).where(
                    Content.id == event.content_id,
                    Content.workspace_id == self._context.workspace_id,
                )
            )
            if content is None:
                raise LookupError("event resource not found")
            if account_id is not None and account_id != content.account_id:
                raise EventPayloadRejected("event resources do not match")
            account_id = content.account_id
        if event.analysis_run_id is not None:
            run = self._session.scalar(
                select(AnalysisRun).where(
                    AnalysisRun.id == event.analysis_run_id,
                    AnalysisRun.workspace_id == self._context.workspace_id,
                )
            )
            if run is None:
                raise LookupError("event resource not found")
            if account_id is not None and account_id != run.account_id:
                raise EventPayloadRejected("event resources do not match")
            account_id = run.account_id
        if event.generation_run_id is not None:
            generation = self._session.scalar(
                select(TextGenerationRun).where(
                    TextGenerationRun.id == event.generation_run_id,
                    TextGenerationRun.workspace_id
                    == self._context.workspace_id,
                )
            )
            if generation is None:
                raise LookupError("event resource not found")
            if account_id is not None and account_id != generation.account_id:
                raise EventPayloadRejected("event resources do not match")
            account_id = generation.account_id
        if event.suggestion_id is not None:
            suggestion = self._session.scalar(
                select(AnalysisSuggestion)
                .join(
                    AnalysisRun,
                    AnalysisRun.id == AnalysisSuggestion.analysis_run_id,
                )
                .where(
                    AnalysisSuggestion.id == event.suggestion_id,
                    AnalysisSuggestion.workspace_id
                    == self._context.workspace_id,
                )
            )
            if suggestion is None:
                raise LookupError("event resource not found")
            run = self._session.get(AnalysisRun, suggestion.analysis_run_id)
            assert run is not None
            if account_id is not None and account_id != run.account_id:
                raise EventPayloadRejected("event resources do not match")
            account_id = run.account_id
        if account_id is None:
            raise EventPayloadRejected("event requires an account-scoped resource")
        account = self._session.scalar(
            select(PlatformAccount).where(
                PlatformAccount.id == account_id,
                PlatformAccount.workspace_id == self._context.workspace_id,
            )
        )
        if account is None:
            raise LookupError("event resource not found")
        return account

    def record(self, event: ProductEventInput) -> ProductEvent | None:
        _validate_properties(event)
        account = self._resolve_account(event)
        fingerprint = _fingerprint(event)
        existing = self._session.scalar(
            select(ProductEventOutbox).where(
                ProductEventOutbox.workspace_id
                == self._context.workspace_id,
                ProductEventOutbox.idempotency_key == event.idempotency_key,
            )
        )
        if existing is not None:
            if existing.payload_fingerprint != fingerprint:
                raise EventIdempotencyConflict(
                    "event idempotency key has another payload"
                )
            return (
                self._session.get(ProductEvent, existing.event_id)
                if existing.event_id is not None
                else None
            )
        entity_id = (
            event.analysis_run_id
            or event.generation_run_id
            or event.suggestion_id
            or event.content_id
            or event.account_id
        )
        if entity_id is None:
            raise EventPayloadRejected("event requires a resource")
        outbox = ProductEventOutbox(
            workspace_id=self._context.workspace_id,
            idempotency_key=event.idempotency_key,
            payload_fingerprint=fingerprint,
            payload={
                "event_name": event.event_name.value,
                "event_version": EVENT_VERSION,
                "entity_type": event.event_name.value.split(".", maxsplit=1)[0],
                "entity_id": str(entity_id),
                "actor_id": (
                    str(self._context.member_id)
                    if self._context.member_id is not None
                    else None
                ),
                "platform": account.platform.value if account else None,
                "account_id": str(account.id),
                "content_id": (
                    str(event.content_id)
                    if event.content_id is not None
                    else None
                ),
                "analysis_run_id": (
                    str(event.analysis_run_id)
                    if event.analysis_run_id is not None
                    else None
                ),
                "generation_run_id": (
                    str(event.generation_run_id)
                    if event.generation_run_id is not None
                    else None
                ),
                "suggestion_id": (
                    str(event.suggestion_id)
                    if event.suggestion_id is not None
                    else None
                ),
                "provider_mode": event.provider_mode,
                "analytics_eligible": (
                    self._context.role != "demo"
                    and event.provider_mode == "real"
                ),
                "properties": event.properties,
            },
        )
        self._session.add(outbox)
        self._session.flush()
        try:
            with self._session.begin_nested():
                return self._publisher(
                    self._session,
                    outbox,
                    self._now(),
                )
        except Exception:
            outbox.attempt_count += 1
            outbox.error_code = "PRODUCT_EVENT_PUBLISH_FAILED"
            self._session.flush()
            return None


def publish_pending_events(
    session: Session,
    *,
    now: Callable[[], datetime] | None = None,
    limit: int = 100,
) -> list[UUID]:
    clock = now or (lambda: datetime.now(UTC))
    pending = list(
        session.scalars(
            select(ProductEventOutbox)
            .where(ProductEventOutbox.processed_at.is_(None))
            .order_by(ProductEventOutbox.created_at, ProductEventOutbox.id)
            .limit(limit)
        )
    )
    processed: list[UUID] = []
    for outbox in pending:
        existing = session.scalar(
            select(ProductEvent).where(
                ProductEvent.workspace_id == outbox.workspace_id,
                ProductEvent.idempotency_key == outbox.idempotency_key,
            )
        )
        if existing is None:
            existing = _publish(session, outbox, clock())
        else:
            outbox.processed_at = clock()
            outbox.event_id = existing.id
            outbox.error_code = None
        processed.append(outbox.id)
        session.flush()
    return processed
