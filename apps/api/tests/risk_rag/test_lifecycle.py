from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.security import WorkspaceContext
from app.modules.content.account_models import Platform
from app.modules.risk_rag.lifecycle import (
    InvalidLifecycleTransition,
    transition_status,
)
from app.modules.risk_rag.models import (
    RiskAuthorizationStatus,
    RiskChunk,
    RiskDocument,
    RiskDocumentScope,
    RiskDocumentStatus,
    RiskSourceLevel,
)
from app.modules.risk_rag.repository import RiskDocumentRepository
from app.modules.workspace.models import Workspace, WorkspaceMember
from app.modules.workspace.permissions import PermissionDenied
from tests.imports.helpers import configured_client


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (RiskDocumentStatus.DRAFT, RiskDocumentStatus.PARSED),
        (RiskDocumentStatus.PARSED, RiskDocumentStatus.PENDING_REVIEW),
        (RiskDocumentStatus.PENDING_REVIEW, RiskDocumentStatus.ACTIVE),
        (RiskDocumentStatus.ACTIVE, RiskDocumentStatus.SUPERSEDED),
        (RiskDocumentStatus.ACTIVE, RiskDocumentStatus.EXPIRED),
    ],
)
def test_legal_lifecycle_transitions(
    current: RiskDocumentStatus,
    target: RiskDocumentStatus,
) -> None:
    reviewer_id: UUID | None = (
        uuid4() if target is RiskDocumentStatus.ACTIVE else None
    )

    assert transition_status(current, target, reviewer_id=reviewer_id) is target


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (RiskDocumentStatus.DRAFT, RiskDocumentStatus.ACTIVE),
        (RiskDocumentStatus.PARSED, RiskDocumentStatus.DRAFT),
        (RiskDocumentStatus.PENDING_REVIEW, RiskDocumentStatus.PARSED),
        (RiskDocumentStatus.ACTIVE, RiskDocumentStatus.PENDING_REVIEW),
        (RiskDocumentStatus.SUPERSEDED, RiskDocumentStatus.ACTIVE),
        (RiskDocumentStatus.EXPIRED, RiskDocumentStatus.ACTIVE),
    ],
)
def test_illegal_skips_and_rollbacks_are_rejected(
    current: RiskDocumentStatus,
    target: RiskDocumentStatus,
) -> None:
    with pytest.raises(InvalidLifecycleTransition, match="not allowed"):
        transition_status(current, target, reviewer_id=uuid4())


def test_activation_requires_a_reviewer() -> None:
    with pytest.raises(InvalidLifecycleTransition, match="reviewer"):
        transition_status(
            RiskDocumentStatus.PENDING_REVIEW,
            RiskDocumentStatus.ACTIVE,
            reviewer_id=None,
        )


@pytest.mark.parametrize(
    "status",
    [RiskDocumentStatus.SUPERSEDED, RiskDocumentStatus.EXPIRED],
)
def test_terminal_states_cannot_transition(status: RiskDocumentStatus) -> None:
    for target in RiskDocumentStatus:
        with pytest.raises(InvalidLifecycleTransition):
            transition_status(status, target, reviewer_id=uuid4())


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as database_session:
        yield database_session


def _private_document(
    *,
    workspace_id: UUID,
    platform: Platform,
    title: str,
    status: RiskDocumentStatus,
    effective_at: datetime,
    reviewer_id: UUID | None,
    version: int = 1,
    previous_version_id: UUID | None = None,
) -> RiskDocument:
    return RiskDocument(
        workspace_id=workspace_id,
        platform=platform,
        scope=RiskDocumentScope.PRIVATE,
        source_level=RiskSourceLevel.S3,
        title=title,
        private_document_id=f"synthetic-{title}",
        authorization_status=RiskAuthorizationStatus.AUTHORIZED,
        status=status,
        version=version,
        effective_at=effective_at,
        reviewed_by=reviewer_id,
        previous_version_id=previous_version_id,
    )


def test_current_documents_are_active_platform_scoped_and_workspace_scoped(
    session: Session,
) -> None:
    now = datetime(2026, 7, 23, 8, tzinfo=UTC)
    workspace_a = Workspace(name="合成风控工作区 A")
    workspace_b = Workspace(name="合成风控工作区 B")
    member_a = WorkspaceMember(
        workspace_id=workspace_a.id,
        display_name="合成审核员 A",
        role="admin",
    )
    member_b = WorkspaceMember(
        workspace_id=workspace_b.id,
        display_name="合成审核员 B",
        role="admin",
    )
    session.add_all([workspace_a, workspace_b, member_a, member_b])
    session.flush()

    visible = _private_document(
        workspace_id=workspace_a.id,
        platform=Platform.DOUYIN,
        title="抖音当前规则",
        status=RiskDocumentStatus.ACTIVE,
        effective_at=now - timedelta(days=1),
        reviewer_id=member_a.id,
    )
    wrong_platform = _private_document(
        workspace_id=workspace_a.id,
        platform=Platform.XIAOHONGSHU,
        title="小红书当前规则",
        status=RiskDocumentStatus.ACTIVE,
        effective_at=now - timedelta(days=1),
        reviewer_id=member_a.id,
    )
    pending = _private_document(
        workspace_id=workspace_a.id,
        platform=Platform.DOUYIN,
        title="待审核规则",
        status=RiskDocumentStatus.PENDING_REVIEW,
        effective_at=now - timedelta(days=1),
        reviewer_id=None,
    )
    future = _private_document(
        workspace_id=workspace_a.id,
        platform=Platform.DOUYIN,
        title="尚未生效规则",
        status=RiskDocumentStatus.ACTIVE,
        effective_at=now + timedelta(days=1),
        reviewer_id=member_a.id,
    )
    other_workspace = _private_document(
        workspace_id=workspace_b.id,
        platform=Platform.DOUYIN,
        title="另一工作区私有规则",
        status=RiskDocumentStatus.ACTIVE,
        effective_at=now - timedelta(days=1),
        reviewer_id=member_b.id,
    )
    session.add_all(
        [visible, wrong_platform, pending, future, other_workspace]
    )
    session.commit()

    repository = RiskDocumentRepository(
        session,
        context=WorkspaceContext(
            workspace_id=workspace_a.id,
            member_id=member_a.id,
            role="admin",
        ),
    )

    assert repository.list_current(platform=Platform.DOUYIN, at=now) == [
        visible
    ]
    assert repository.get(other_workspace.id) is None


def test_public_active_documents_are_visible_but_private_chunks_stay_scoped(
    session: Session,
) -> None:
    now = datetime(2026, 7, 23, 8, tzinfo=UTC)
    workspace_a = Workspace(name="合成知识库 A")
    workspace_b = Workspace(name="合成知识库 B")
    member_a = WorkspaceMember(
        workspace_id=workspace_a.id,
        display_name="合成管理员 A",
        role="admin",
    )
    session.add_all([workspace_a, workspace_b, member_a])
    session.flush()
    public = RiskDocument(
        workspace_id=None,
        platform=Platform.DOUYIN,
        scope=RiskDocumentScope.PUBLIC,
        source_level=RiskSourceLevel.S1,
        title="合成公开规则摘要",
        source_url="https://example.invalid/synthetic-rule",
        authorization_status=RiskAuthorizationStatus.NOT_REQUIRED,
        status=RiskDocumentStatus.ACTIVE,
        version=1,
        published_at=now - timedelta(days=3),
        effective_at=now - timedelta(days=2),
        accessed_at=now - timedelta(days=1),
        reviewed_by=member_a.id,
    )
    private = _private_document(
        workspace_id=workspace_b.id,
        platform=Platform.DOUYIN,
        title="合成私有案例",
        status=RiskDocumentStatus.ACTIVE,
        effective_at=now - timedelta(days=1),
        reviewer_id=member_a.id,
    )
    session.add_all([public, private])
    session.flush()
    private_chunk = RiskChunk(
        workspace_id=workspace_b.id,
        document_id=private.id,
        platform=Platform.DOUYIN,
        scope=RiskDocumentScope.PRIVATE,
        chunk_index=0,
        source_location="人工段落 1",
        text="完全虚构且不包含真实平台规则的测试文本。",
    )
    session.add(private_chunk)
    session.commit()

    repository = RiskDocumentRepository(
        session,
        context=WorkspaceContext(
            workspace_id=workspace_a.id,
            member_id=member_a.id,
            role="admin",
        ),
    )

    assert repository.list_current(platform=Platform.DOUYIN, at=now) == [
        public
    ]
    assert repository.list_chunks(private.id) == []


def test_workspace_admin_cannot_transition_system_public_document(
    session: Session,
) -> None:
    workspace = Workspace(name="合成公共库权限工作区")
    admin = WorkspaceMember(
        workspace_id=workspace.id,
        display_name="合成公共库管理员",
        role="admin",
    )
    session.add_all([workspace, admin])
    session.flush()
    public = RiskDocument(
        workspace_id=None,
        platform=Platform.DOUYIN,
        scope=RiskDocumentScope.PUBLIC,
        source_level=RiskSourceLevel.S1,
        title="人工合成系统公共材料",
        source_url="https://example.invalid/system-public",
        authorization_status=RiskAuthorizationStatus.AUTHORIZED,
        status=RiskDocumentStatus.DRAFT,
        version=1,
    )
    session.add(public)
    session.commit()
    repository = RiskDocumentRepository(
        session,
        context=WorkspaceContext(
            workspace_id=workspace.id,
            member_id=admin.id,
            role="admin",
        ),
    )

    with pytest.raises(PermissionDenied, match="system public"):
        repository.transition(public.id, RiskDocumentStatus.PARSED)


def test_historical_lookup_can_trace_superseded_version_in_same_workspace(
    session: Session,
) -> None:
    now = datetime(2026, 7, 23, 8, tzinfo=UTC)
    workspace = Workspace(name="合成版本工作区")
    reviewer = WorkspaceMember(
        workspace_id=workspace.id,
        display_name="合成版本审核员",
        role="admin",
    )
    session.add_all([workspace, reviewer])
    session.flush()
    old = _private_document(
        workspace_id=workspace.id,
        platform=Platform.XIAOHONGSHU,
        title="合成规则 v1",
        status=RiskDocumentStatus.SUPERSEDED,
        effective_at=now - timedelta(days=30),
        reviewer_id=reviewer.id,
    )
    session.add(old)
    session.flush()
    current = _private_document(
        workspace_id=workspace.id,
        platform=Platform.XIAOHONGSHU,
        title="合成规则 v2",
        status=RiskDocumentStatus.ACTIVE,
        effective_at=now - timedelta(days=1),
        reviewer_id=reviewer.id,
        version=2,
        previous_version_id=old.id,
    )
    session.add(current)
    session.commit()

    repository = RiskDocumentRepository(
        session,
        context=WorkspaceContext(
            workspace_id=workspace.id,
            member_id=reviewer.id,
            role="admin",
        ),
    )

    assert repository.list_current(
        platform=Platform.XIAOHONGSHU, at=now
    ) == [current]
    assert repository.get_historical(old.id) is old
    assert repository.version_chain(current.id) == [current, old]


def _create_and_login_admin(
    client: TestClient,
    *,
    name: str,
) -> tuple[str, str]:
    workspace = client.post("/v1/workspaces", json={"name": name}).json()
    login = client.post(
        "/v1/sessions/invite",
        json={
            "code": workspace["admin_code"],
            "display_name": f"{name}管理员",
        },
    ).json()
    return workspace["workspace_id"], login["csrf_token"]


def _private_document_payload(
    *,
    title: str = "人工合成风控文档",
    platform: str = "douyin",
) -> dict[str, object]:
    return {
        "platform": platform,
        "source_level": "S3",
        "title": title,
        "private_document_id": f"synthetic-{platform}-{title}",
        "authorization_status": "authorized",
        "published_at": "2026-07-20T08:00:00Z",
        "effective_at": "2026-07-21T08:00:00Z",
        "accessed_at": "2026-07-22T08:00:00Z",
    }


def test_private_knowledge_is_readable_but_only_admins_can_manage_it() -> None:
    with configured_client() as (admin_client, _):
        workspace_id, admin_csrf = _create_and_login_admin(
            admin_client,
            name="合成权限工作区",
        )
        created = admin_client.post(
            f"/v1/workspaces/{workspace_id}/risk-documents",
            headers={"X-CSRF-Token": admin_csrf},
            json=_private_document_payload(),
        )
        assert created.status_code == 201, created.text
        document_id = created.json()["id"]
        assert created.json()["scope"] == "private"
        assert created.json()["status"] == "draft"

        editor_code = admin_client.post(
            f"/v1/workspaces/{workspace_id}/members/codes",
            headers={"X-CSRF-Token": admin_csrf},
            json={"role": "editor"},
        ).json()["code"]
        with TestClient(admin_client.app) as editor_client:
            editor_login = editor_client.post(
                "/v1/sessions/invite",
                json={
                    "code": editor_code,
                    "display_name": "合成编辑者",
                },
            ).json()
            editor_csrf = editor_login["csrf_token"]

            readable = editor_client.get(
                f"/v1/workspaces/{workspace_id}/risk-documents/{document_id}"
            )
            assert readable.status_code == 200
            forbidden = editor_client.post(
                f"/v1/workspaces/{workspace_id}/risk-documents",
                headers={"X-CSRF-Token": editor_csrf},
                json=_private_document_payload(title="编辑者不可创建"),
            )
            assert forbidden.status_code == 403


def test_cross_workspace_private_document_access_returns_404() -> None:
    with configured_client() as (workspace_a_client, _):
        workspace_a, csrf_a = _create_and_login_admin(
            workspace_a_client,
            name="合成隔离工作区 A",
        )
        created = workspace_a_client.post(
            f"/v1/workspaces/{workspace_a}/risk-documents",
            headers={"X-CSRF-Token": csrf_a},
            json=_private_document_payload(),
        )
        assert created.status_code == 201, created.text
        document_id = created.json()["id"]

        with TestClient(workspace_a_client.app) as workspace_b_client:
            workspace_b, _ = _create_and_login_admin(
                workspace_b_client,
                name="合成隔离工作区 B",
            )
            hidden = workspace_b_client.get(
                f"/v1/workspaces/{workspace_b}/risk-documents/{document_id}"
            )

        assert hidden.status_code == 404


def test_document_api_enforces_lifecycle_and_current_platform_filter() -> None:
    with configured_client() as (client, _):
        workspace_id, csrf = _create_and_login_admin(
            client,
            name="合成生命周期工作区",
        )
        created = client.post(
            f"/v1/workspaces/{workspace_id}/risk-documents",
            headers={"X-CSRF-Token": csrf},
            json=_private_document_payload(),
        )
        document_id = created.json()["id"]

        invalid = client.post(
            (
                f"/v1/workspaces/{workspace_id}/risk-documents/"
                f"{document_id}/transitions"
            ),
            headers={"X-CSRF-Token": csrf},
            json={"status": "active"},
        )
        assert invalid.status_code == 409

        for status in ("parsed", "pending_review", "active"):
            transitioned = client.post(
                (
                    f"/v1/workspaces/{workspace_id}/risk-documents/"
                    f"{document_id}/transitions"
                ),
                headers={"X-CSRF-Token": csrf},
                json={"status": status},
            )
            assert transitioned.status_code == 200, transitioned.text
        assert transitioned.json()["reviewed_by"] is not None

        douyin = client.get(
            f"/v1/workspaces/{workspace_id}/risk-documents/current",
            params={"platform": "douyin", "at": "2026-07-23T08:00:00Z"},
        )
        xiaohongshu = client.get(
            f"/v1/workspaces/{workspace_id}/risk-documents/current",
            params={
                "platform": "xiaohongshu",
                "at": "2026-07-23T08:00:00Z",
            },
        )

        assert [item["id"] for item in douyin.json()] == [document_id]
        assert xiaohongshu.json() == []
