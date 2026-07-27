from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import WorkspaceContext
from app.modules.analytics.events import (
    EventIdempotencyConflict,
    EventName,
    EventPayloadRejected,
    EventService,
    ProductEventInput,
    publish_pending_events,
)
from app.modules.analysis.models import ProductEvent, ProductEventOutbox
from app.modules.content.account_models import Platform
from app.modules.workspace.models import Workspace
from tests.imports.helpers import configured_client, create_workspace_account


NOW = datetime(2026, 7, 27, 1, 2, 3, tzinfo=UTC)


def _context(client, engine, workspace_id: str) -> WorkspaceContext:
    from app.modules.workspace.auth import InviteAuthService

    token = client.cookies.get("session")
    assert token is not None
    with Session(engine) as session:
        context = InviteAuthService(session).authenticate(token)
        assert context is not None
        assert context.workspace_id == UUID(workspace_id)
        return context


def test_event_is_versioned_server_timed_minimal_and_idempotent() -> None:
    with configured_client() as (client, engine):
        workspace_id, _, account = create_workspace_account(client)
        context = _context(client, engine, workspace_id)
        event_input = ProductEventInput(
            event_name=EventName.COLLECTION_STARTED,
            idempotency_key="collection-started-once",
            account_id=UUID(account["id"]),
            properties={"source": "manual"},
        )
        with Session(engine, expire_on_commit=False) as session:
            service = EventService(session, context, now=lambda: NOW)
            first = service.record(event_input)
            repeated = service.record(event_input)
            session.commit()

            assert first is not None
            assert repeated is not None
            assert first.id == repeated.id
            assert first.event_version == 1
            assert first.server_occurred_at == NOW
            assert first.workspace_id == context.workspace_id
            assert first.actor_id == context.member_id
            assert first.platform is Platform.DOUYIN
            assert first.account_id == UUID(account["id"])
            assert first.properties == {"source": "manual"}
            assert first.provider_mode == "real"
            assert first.analytics_eligible
            assert (
                len(
                    list(
                        session.scalars(
                            select(ProductEvent).where(
                                ProductEvent.workspace_id
                                == context.workspace_id
                            )
                        )
                    )
                )
                == 1
            )


def test_idempotency_conflict_and_sensitive_or_unknown_payload_are_rejected() -> None:
    with configured_client() as (client, engine):
        workspace_id, _, account = create_workspace_account(client)
        context = _context(client, engine, workspace_id)
        with Session(engine) as session:
            service = EventService(session, context, now=lambda: NOW)
            service.record(
                ProductEventInput(
                    event_name=EventName.COLLECTION_STARTED,
                    idempotency_key="same-key",
                    account_id=UUID(account["id"]),
                    properties={"source": "manual"},
                )
            )
            with pytest.raises(EventIdempotencyConflict):
                service.record(
                    ProductEventInput(
                        event_name=EventName.COLLECTION_STARTED,
                        idempotency_key="same-key",
                        account_id=UUID(account["id"]),
                        properties={"source": "xlsx"},
                    )
                )
            for properties in (
                {"title": "不能保存完整标题"},
                {"prompt": "不能保存模型提示词"},
                {"source": "manual", "unknown": True},
                {"source": "x" * 81},
            ):
                with pytest.raises(EventPayloadRejected):
                    service.record(
                        ProductEventInput(
                            event_name=EventName.COLLECTION_STARTED,
                            idempotency_key=f"rejected-{len(str(properties))}",
                            account_id=UUID(account["id"]),
                            properties=properties,
                        )
                    )


def test_event_resources_are_workspace_and_platform_derived_not_client_claimed() -> None:
    with configured_client() as (client, engine):
        workspace_id, _, account = create_workspace_account(client)
        context = _context(client, engine, workspace_id)
        other_workspace_id, _, other_account = create_workspace_account(
            client,
            workspace_name="事件隔离工作区",
            platform="xiaohongshu",
        )
        with Session(engine) as session:
            service = EventService(session, context, now=lambda: NOW)
            with pytest.raises(LookupError):
                service.record(
                    ProductEventInput(
                        event_name=EventName.COLLECTION_STARTED,
                        idempotency_key="cross-workspace",
                        account_id=UUID(other_account["id"]),
                        properties={"source": "manual"},
                    )
                )
            assert (
                session.scalar(
                    select(ProductEvent).where(
                        ProductEvent.workspace_id == UUID(other_workspace_id)
                    )
                )
                is None
            )


def test_demo_and_mock_events_are_retained_but_excluded_from_real_metrics() -> None:
    with configured_client() as (client, engine):
        workspace_id, _, account = create_workspace_account(client)
        context = _context(client, engine, workspace_id)
        with Session(engine, expire_on_commit=False) as session:
            mock_event = EventService(
                session, context, now=lambda: NOW
            ).record(
                ProductEventInput(
                    event_name=EventName.ANALYSIS_STARTED,
                    idempotency_key="mock-analysis",
                    account_id=UUID(account["id"]),
                    properties={"trigger_kind": "manual"},
                    provider_mode="mock",
                )
            )
            demo_context = WorkspaceContext(
                workspace_id=context.workspace_id,
                member_id=context.member_id,
                role="demo",
            )
            demo_event = EventService(
                session, demo_context, now=lambda: NOW
            ).record(
                ProductEventInput(
                    event_name=EventName.COLLECTION_STARTED,
                    idempotency_key="demo-collection",
                    account_id=UUID(account["id"]),
                    properties={"source": "manual"},
                )
            )
            session.commit()
            assert mock_event is not None
            assert demo_event is not None
            assert not mock_event.analytics_eligible
            assert not demo_event.analytics_eligible


def test_event_publish_failure_keeps_outbox_for_idempotent_compensation() -> None:
    with configured_client() as (client, engine):
        workspace_id, _, account = create_workspace_account(client)
        context = _context(client, engine, workspace_id)
        with Session(engine) as session:
            workspace = session.get(Workspace, context.workspace_id)
            assert workspace is not None
            workspace.name = "业务写入已提交"
            event = EventService(
                session,
                context,
                now=lambda: NOW,
                publisher=lambda *_: (_ for _ in ()).throw(
                    RuntimeError("synthetic event insert failure")
                ),
            ).record(
                ProductEventInput(
                    event_name=EventName.COLLECTION_CONFIRMED,
                    idempotency_key="reliable-event",
                    account_id=UUID(account["id"]),
                    properties={"source": "manual"},
                )
            )
            session.commit()
            assert event is None

        with Session(engine) as session:
            workspace = session.get(Workspace, context.workspace_id)
            assert workspace is not None
            assert workspace.name == "业务写入已提交"
            outbox = session.scalar(
                select(ProductEventOutbox).where(
                    ProductEventOutbox.idempotency_key == "reliable-event"
                )
            )
            assert outbox is not None
            assert outbox.processed_at is None
            assert (
                session.scalar(
                    select(ProductEvent).where(
                        ProductEvent.idempotency_key == "reliable-event"
                    )
                )
                is None
            )
            assert publish_pending_events(
                session,
                now=lambda: NOW + timedelta(seconds=1),
            ) == [outbox.id]
            session.commit()
            assert outbox.processed_at == NOW + timedelta(seconds=1)
            assert session.scalar(
                select(ProductEvent).where(
                    ProductEvent.idempotency_key == "reliable-event"
                )
            ) is not None
            assert publish_pending_events(session) == []


def test_rolled_back_business_transaction_leaves_no_success_event() -> None:
    with configured_client() as (client, engine):
        workspace_id, _, account = create_workspace_account(client)
        context = _context(client, engine, workspace_id)
        with Session(engine) as session:
            event = EventService(session, context, now=lambda: NOW).record(
                ProductEventInput(
                    event_name=EventName.COLLECTION_STARTED,
                    idempotency_key="rolled-back-action",
                    account_id=UUID(account["id"]),
                    properties={"source": "manual"},
                )
            )
            assert event is not None
            session.rollback()
        with Session(engine) as session:
            assert session.scalar(
                select(ProductEvent).where(
                    ProductEvent.idempotency_key == "rolled-back-action"
                )
            ) is None
            assert session.scalar(
                select(ProductEventOutbox).where(
                    ProductEventOutbox.idempotency_key
                    == "rolled-back-action"
                )
            ) is None
