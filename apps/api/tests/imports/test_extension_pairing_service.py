from concurrent.futures import Future, ThreadPoolExecutor
import os
from datetime import UTC, datetime, timedelta
from queue import Queue
from threading import Barrier
from time import monotonic, sleep
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import main as _app  # noqa: F401
from app.core.database import Base
from app.modules.imports.extension_pairing import (
    ExtensionPairingService,
    PairingCodeRateLimited,
    PairingCodeUnavailable,
)
from app.modules.imports.models import (
    ExtensionPairingCode,
    ExtensionToken,
    ExtensionTokenScope,
)
from app.modules.workspace.models import MemberRole, Workspace, WorkspaceMember


def _session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine, expire_on_commit=False)


def _workspace_with_editor(session: Session) -> tuple[Workspace, WorkspaceMember]:
    workspace = Workspace(name="配对服务工作区")
    session.add(workspace)
    session.flush()
    editor = WorkspaceMember(
        workspace_id=workspace.id,
        display_name="编辑",
        role=MemberRole.EDITOR,
    )
    session.add(editor)
    session.commit()
    return workspace, editor


def _wait_for_database_lock(
    admin_engine: Engine,
    *,
    worker_pid: int,
    future: Future[str],
) -> None:
    deadline = monotonic() + 5
    while monotonic() < deadline:
        if future.done():
            raise AssertionError(
                "redemption finished before waiting for the member lock: "
                f"result={future.result()}"
            )
        with admin_engine.connect() as connection:
            waiting = connection.scalar(
                text(
                    "SELECT wait_event_type = 'Lock' "
                    "FROM pg_stat_activity "
                    "WHERE pid = :worker_pid"
                ),
                {"worker_pid": worker_pid},
            )
        if waiting:
            return
        sleep(0.01)
    with admin_engine.connect() as connection:
        activities = connection.execute(
            text(
                "SELECT application_name, state, wait_event_type "
                "FROM pg_stat_activity "
                "WHERE pid = :worker_pid"
            ),
            {"worker_pid": worker_pid},
        ).all()
    raise AssertionError(
        f"redemption did not wait for the member lock: {activities}"
    )


def test_creates_plaintext_excluded_code_and_reuses_existing_member() -> None:
    session = _session()
    workspace, editor = _workspace_with_editor(session)
    service = ExtensionPairingService(session)

    created = service.create(workspace_id=workspace.id, member_id=editor.id)
    assert len(created.code) == 8
    assert created.code not in str(session.scalar(select(ExtensionPairingCode)))

    before_members = session.scalar(
        select(func.count()).select_from(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace.id
        )
    )
    issued = service.redeem(created.code, client_id="operations-capture-extension")
    after_members = session.scalar(
        select(func.count()).select_from(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace.id
        )
    )
    assert issued.member_id == editor.id
    assert after_members == before_members
    assert issued.expires_at - issued.issued_at == timedelta(hours=8)
    assert issued.scopes == (
        ExtensionTokenScope.CAPTURE_CREATE.value,
        ExtensionTokenScope.CAPTURE_UPLOAD.value,
        ExtensionTokenScope.CAPTURE_READ.value,
    )


def test_only_newest_unused_code_for_member_can_be_redeemed() -> None:
    session = _session()
    workspace, editor = _workspace_with_editor(session)
    service = ExtensionPairingService(session)

    first = service.create(workspace_id=workspace.id, member_id=editor.id)
    second = service.create(workspace_id=workspace.id, member_id=editor.id)

    with pytest.raises(PairingCodeUnavailable):
        service.redeem(first.code, client_id="operations-capture-extension")
    issued = service.redeem(second.code, client_id="operations-capture-extension")
    records = list(session.scalars(select(ExtensionPairingCode)))
    assert issued.member_id == editor.id
    assert len(records) == 2
    assert sum(record.revoked_at is None and record.used_at is None for record in records) == 0


def test_expired_code_is_indistinguishable_from_an_unavailable_code() -> None:
    session = _session()
    workspace, editor = _workspace_with_editor(session)
    current = datetime(2026, 8, 10, tzinfo=UTC)
    service = ExtensionPairingService(session, now=lambda: current)
    created = service.create(workspace_id=workspace.id, member_id=editor.id)
    assert created.expires_at - current == timedelta(minutes=5)

    current += timedelta(minutes=6)
    with pytest.raises(PairingCodeUnavailable):
        service.redeem(created.code, client_id="operations-capture-extension")


def test_code_can_only_be_redeemed_once() -> None:
    session = _session()
    workspace, editor = _workspace_with_editor(session)
    service = ExtensionPairingService(session)
    created = service.create(workspace_id=workspace.id, member_id=editor.id)

    service.redeem(created.code, client_id="operations-capture-extension")
    with pytest.raises(PairingCodeUnavailable):
        service.redeem(created.code, client_id="operations-capture-extension")


def test_simultaneous_redemption_issues_exactly_one_token() -> None:
    database_url = os.getenv(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://operations_ai:local-development-only"
        "@127.0.0.1:55432/operations_ai",
    )
    schema = f"pairing_concurrency_{uuid4().hex}"
    admin_engine = create_engine(database_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(text(f"CREATE SCHEMA {schema}"))
    schema_url = make_url(database_url).update_query_dict(
        {"options": f"-csearch_path={schema}"}
    )
    engine = create_engine(schema_url)
    Workspace.__table__.create(engine)
    WorkspaceMember.__table__.create(engine)
    ExtensionToken.__table__.create(engine)
    ExtensionPairingCode.__table__.create(engine)
    session = Session(engine, expire_on_commit=False)
    workspace, editor = _workspace_with_editor(session)
    created = ExtensionPairingService(session).create(
        workspace_id=workspace.id,
        member_id=editor.id,
    )
    session.commit()
    session.close()
    barrier = Barrier(2)

    def redeem() -> str:
        with Session(engine) as redemption_session:
            try:
                barrier.wait()
                with redemption_session.begin():
                    return ExtensionPairingService(redemption_session).redeem(
                        created.code,
                        client_id="operations-capture-extension",
                    ).access_token
            except PairingCodeUnavailable:
                return "unavailable"

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: redeem(), range(2)))
    finally:
        engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin_engine.dispose()

    assert results.count("unavailable") == 1
    assert len([result for result in results if result != "unavailable"]) == 1


def test_create_and_redeem_lock_member_before_pairing_code_without_deadlock() -> None:
    database_url = os.getenv(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://operations_ai:local-development-only"
        "@127.0.0.1:55432/operations_ai",
    )
    schema = f"pairing_lock_order_{uuid4().hex}"
    admin_engine = create_engine(database_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(text(f"CREATE SCHEMA {schema}"))
    schema_url = make_url(database_url).update_query_dict(
        {"options": f"-csearch_path={schema}"}
    )
    engine = create_engine(schema_url)
    worker_engine = create_engine(schema_url)
    Workspace.__table__.create(engine)
    WorkspaceMember.__table__.create(engine)
    ExtensionToken.__table__.create(engine)
    ExtensionPairingCode.__table__.create(engine)

    try:
        with Session(engine, expire_on_commit=False) as session:
            workspace, editor = _workspace_with_editor(session)
            original = ExtensionPairingService(session).create(
                workspace_id=workspace.id,
                member_id=editor.id,
            )
            session.commit()

            worker_pids: Queue[int] = Queue()

            def redeem() -> str:
                with Session(worker_engine) as redemption_session:
                    try:
                        with redemption_session.begin():
                            worker_pids.put(
                                int(
                                    redemption_session.scalar(
                                        text("SELECT pg_backend_pid()")
                                    )
                                )
                            )
                            return ExtensionPairingService(
                                redemption_session
                            ).redeem(
                                original.code,
                                client_id="operations-capture-extension",
                            ).access_token
                    except PairingCodeUnavailable:
                        return "unavailable"

            with ThreadPoolExecutor(max_workers=1) as executor:
                with session.begin():
                    session.scalar(
                        select(WorkspaceMember)
                        .where(WorkspaceMember.id == editor.id)
                        .with_for_update()
                    )
                    result = executor.submit(redeem)
                    worker_pid = worker_pids.get(timeout=5)
                    _wait_for_database_lock(
                        admin_engine,
                        worker_pid=worker_pid,
                        future=result,
                    )
                    replacement = ExtensionPairingService(session).create(
                        workspace_id=workspace.id,
                        member_id=editor.id,
                    )
            assert replacement.code != original.code
            assert result.result(timeout=5) == "unavailable"
    finally:
        worker_engine.dispose()
        engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin_engine.dispose()


def test_revoked_member_cannot_redeem_code() -> None:
    session = _session()
    workspace, editor = _workspace_with_editor(session)
    service = ExtensionPairingService(session)
    created = service.create(workspace_id=workspace.id, member_id=editor.id)
    editor.revoked_at = datetime.now(UTC)
    session.commit()

    with pytest.raises(PairingCodeUnavailable):
        service.redeem(created.code, client_id="operations-capture-extension")


def test_invalid_redemptions_are_rate_limited_without_revealing_code_state() -> None:
    session = _session()
    service = ExtensionPairingService(session)

    for _ in range(10):
        with pytest.raises(PairingCodeUnavailable):
            service.redeem("ABCD-1234", client_id="operations-capture-extension")
    with pytest.raises(PairingCodeRateLimited):
        service.redeem("ABCD-1234", client_id="operations-capture-extension")
