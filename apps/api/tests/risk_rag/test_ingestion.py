import socket

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.security import WorkspaceContext
from app.core.storage import S3Storage
from app.modules.content.account_models import Platform
from app.modules.risk_rag.chunking import chunk_document
from app.modules.risk_rag.ingestion import (
    DuplicateRiskDocument,
    RiskIngestionService,
    is_open_source_seed_eligible,
)
from app.modules.risk_rag.models import (
    RiskAuthorizationStatus,
    RiskChunk,
    RiskDocument,
    RiskDocumentScope,
    RiskDocumentStatus,
    RiskSourceLevel,
)
from app.modules.style_facts.url_safety import UnsafeSourceUrl
from app.modules.workspace.models import Workspace, WorkspaceMember
from app.modules.workspace.permissions import PermissionDenied


class RecordingStorage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.put_count = 0

    def put_object(
        self,
        object_key: str,
        content: bytes,
        *,
        mime_type: str,
    ) -> None:
        self.put_count += 1
        self.objects[object_key] = (content, mime_type)


class RecordingOpener:
    def __init__(self) -> None:
        self.requests = []

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

    def open(self, request, *, timeout: int):
        assert timeout == 10
        self.requests.append(request)
        return self._Response()


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as database_session:
        yield database_session


def _context_and_document(
    session: Session,
    *,
    source_url: str | None = None,
    private_document_id: str | None = "synthetic-risk-file",
) -> tuple[WorkspaceContext, RiskDocument]:
    workspace = Workspace(name="合成安全入库工作区")
    member = WorkspaceMember(
        workspace_id=workspace.id,
        display_name="合成入库管理员",
        role="admin",
    )
    session.add_all([workspace, member])
    session.flush()
    document = RiskDocument(
        workspace_id=workspace.id,
        platform=Platform.DOUYIN,
        scope=RiskDocumentScope.PRIVATE,
        source_level=RiskSourceLevel.S3,
        title="人工合成风控材料",
        source_url=source_url,
        private_document_id=private_document_id,
        authorization_status=RiskAuthorizationStatus.AUTHORIZED,
        status=RiskDocumentStatus.DRAFT,
        version=1,
    )
    session.add(document)
    session.commit()
    return (
        WorkspaceContext(
            workspace_id=workspace.id,
            member_id=member.id,
            role="admin",
        ),
        document,
    )


def _resolver_for(*addresses: str):
    def resolve(host: str, port: int, *, type: int):
        assert type == socket.SOCK_STREAM
        return [
            (
                socket.AF_INET6 if ":" in address else socket.AF_INET,
                type,
                6,
                "",
                (address, port),
            )
            for address in addresses
        ]

    return resolve


def test_file_is_untrusted_and_raw_bytes_only_enter_object_storage(
    session: Session,
) -> None:
    context, document = _context_and_document(session)
    storage = RecordingStorage()
    content = (
        "第一条：这是人工生成的测试条款。\n"
        "第二条：不得把测试文本当作真实平台规则。\n"
    ).encode()

    ingested = RiskIngestionService(
        session,
        context,
        storage=storage,
    ).ingest_file(
        document.id,
        file_name="synthetic-rules.txt",
        mime_type="text/plain",
        content=content,
        redistribution_authorized=False,
    )

    assert ingested.untrusted_data is True
    assert ingested.object_key in storage.objects
    assert storage.objects[ingested.object_key] == (content, "text/plain")
    assert ingested.content_sha256 is not None
    assert len(ingested.content_sha256) == 64
    assert ingested.status is RiskDocumentStatus.PARSED
    assert not hasattr(ingested, "raw_content")
    assert is_open_source_seed_eligible(ingested) is False


def test_s3_storage_can_write_server_side_risk_source_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = S3Storage()
    opener = RecordingOpener()
    monkeypatch.setattr(storage, "_ensure_bucket", lambda: None)
    monkeypatch.setattr(storage, "_opener", opener)

    storage.put_object(
        "workspaces/synthetic/risk-knowledge/source.txt",
        b"synthetic source",
        mime_type="text/plain",
    )

    request = opener.requests[0]
    assert request.get_method() == "PUT"
    assert request.data == b"synthetic source"
    assert request.headers["Content-type"] == "text/plain"
    assert "risk-knowledge/source.txt" in request.full_url


def test_retry_is_idempotent_and_duplicate_content_is_rejected(
    session: Session,
) -> None:
    context, document = _context_and_document(session)
    storage = RecordingStorage()
    service = RiskIngestionService(session, context, storage=storage)
    content = b"Synthetic clause A.\nSynthetic clause B."

    first = service.ingest_file(
        document.id,
        file_name="synthetic.txt",
        mime_type="text/plain",
        content=content,
        redistribution_authorized=True,
    )
    retried = service.ingest_file(
        document.id,
        file_name="synthetic.txt",
        mime_type="text/plain",
        content=content,
        redistribution_authorized=True,
    )

    assert retried is first
    assert storage.put_count == 1
    assert is_open_source_seed_eligible(first) is False

    _, duplicate = _context_and_document(session)
    duplicate.workspace_id = context.workspace_id
    session.commit()
    with pytest.raises(DuplicateRiskDocument) as caught:
        service.ingest_file(
            duplicate.id,
            file_name="copy.txt",
            mime_type="text/plain",
            content=content,
            redistribution_authorized=True,
        )
    assert caught.value.existing_document_id == first.id
    assert storage.put_count == 1


def test_open_source_seed_requires_public_scope_and_redistribution_rights() -> None:
    public = RiskDocument(
        workspace_id=None,
        platform=Platform.DOUYIN,
        scope=RiskDocumentScope.PUBLIC,
        source_level=RiskSourceLevel.S1,
        title="人工合成且明确允许再分发的公开材料",
        source_url="https://example.invalid/authorized-synthetic",
        authorization_status=RiskAuthorizationStatus.AUTHORIZED,
        status=RiskDocumentStatus.PARSED,
        version=1,
        redistribution_authorized=True,
    )
    unclear_rights = RiskDocument(
        workspace_id=None,
        platform=Platform.DOUYIN,
        scope=RiskDocumentScope.PUBLIC,
        source_level=RiskSourceLevel.S1,
        title="人工合成但未声明再分发授权的公开材料",
        source_url="https://example.invalid/unclear-synthetic",
        authorization_status=RiskAuthorizationStatus.AUTHORIZED,
        status=RiskDocumentStatus.PARSED,
        version=1,
        redistribution_authorized=False,
    )

    assert is_open_source_seed_eligible(public) is True
    assert is_open_source_seed_eligible(unclear_rights) is False


def test_workspace_admin_cannot_ingest_system_public_library(
    session: Session,
) -> None:
    context, _ = _context_and_document(session)
    public = RiskDocument(
        workspace_id=None,
        platform=Platform.DOUYIN,
        scope=RiskDocumentScope.PUBLIC,
        source_level=RiskSourceLevel.S1,
        title="人工合成公开系统材料",
        source_url="https://example.invalid/system-synthetic",
        authorization_status=RiskAuthorizationStatus.AUTHORIZED,
        status=RiskDocumentStatus.DRAFT,
        version=1,
    )
    session.add(public)
    session.commit()

    with pytest.raises(PermissionDenied, match="system public"):
        RiskIngestionService(
            session,
            context,
            storage=RecordingStorage(),
        ).ingest_file(
            public.id,
            file_name="synthetic.txt",
            mime_type="text/plain",
            content=b"synthetic public content",
            redistribution_authorized=True,
        )


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1/internal",
        "http://169.254.169.254/latest/meta-data",
    ],
)
def test_web_ingestion_rejects_non_public_targets(
    session: Session,
    url: str,
) -> None:
    context, document = _context_and_document(
        session,
        source_url=url,
        private_document_id=None,
    )

    with pytest.raises(UnsafeSourceUrl):
        RiskIngestionService(
            session,
            context,
            storage=RecordingStorage(),
        ).prepare_web_source(
            document.id,
            resolver=_resolver_for("127.0.0.1"),
        )


def test_web_ingestion_pins_only_public_dns_answers(session: Session) -> None:
    context, document = _context_and_document(
        session,
        source_url="https://risk.example.invalid/synthetic",
        private_document_id=None,
    )

    prepared = RiskIngestionService(
        session,
        context,
        storage=RecordingStorage(),
    ).prepare_web_source(
        document.id,
        resolver=_resolver_for("93.184.216.34"),
    )

    assert prepared.resolved_ips == ["93.184.216.34"]
    assert prepared.untrusted_data is True


def test_chunking_preserves_chapter_clause_and_part_locations() -> None:
    text = (
        "第一章 合成总则\n"
        "第一条 这是人工生成的测试条款。\n"
        "补充句仅用于验证连续文本归属。\n"
        "第二条 这是一段刻意较长的人工测试条款，用来验证超过长度后仍然保留"
        "原条款位置，而不代表任何真实平台要求。\n"
        "第二章 合成附则\n"
        "第三条 最后一条人工测试内容。\n"
    )

    chunks = chunk_document(text, max_chars=48)

    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert chunks[0].source_location == "第一章 合成总则 > 第一条"
    assert "补充句" in chunks[0].text
    assert [chunk.source_location for chunk in chunks[1:-1]] == [
        "第一章 合成总则 > 第二条#part-1",
        "第一章 合成总则 > 第二条#part-2",
    ]
    assert chunks[-1].source_location == "第二章 合成附则 > 第三条"
    assert "".join(chunk.text for chunk in chunks[1:-1]).replace("\n", "") == (
        "第二条 这是一段刻意较长的人工测试条款，用来验证超过长度后仍然保留"
        "原条款位置，而不代表任何真实平台要求。"
    )


def test_ingestion_persists_scoped_chunks_with_source_locations(
    session: Session,
) -> None:
    context, document = _context_and_document(session)
    content = (
        "第一章 人工测试\n"
        "第一条 合成条款一。\n"
        "第二条 合成条款二。\n"
    ).encode()

    RiskIngestionService(
        session,
        context,
        storage=RecordingStorage(),
    ).ingest_file(
        document.id,
        file_name="synthetic-clauses.txt",
        mime_type="text/plain",
        content=content,
        redistribution_authorized=False,
    )
    chunks = session.query(RiskChunk).order_by(RiskChunk.chunk_index).all()

    assert [chunk.workspace_id for chunk in chunks] == [
        context.workspace_id,
        context.workspace_id,
    ]
    assert [chunk.platform for chunk in chunks] == [
        Platform.DOUYIN,
        Platform.DOUYIN,
    ]
    assert [chunk.scope for chunk in chunks] == [
        RiskDocumentScope.PRIVATE,
        RiskDocumentScope.PRIVATE,
    ]
    assert [chunk.source_location for chunk in chunks] == [
        "第一章 人工测试 > 第一条",
        "第一章 人工测试 > 第二条",
    ]
