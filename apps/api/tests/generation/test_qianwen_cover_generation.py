from datetime import UTC, datetime, timedelta
import hashlib
from io import BytesIO
from uuid import UUID, uuid4

from PIL import Image
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.security import WorkspaceContext
from app.core.storage import StoredObject
from app.modules.content.account_models import (
    BenchmarkProfile,
    ObjectiveProfile,
    Platform,
    PlatformAccount,
)
from app.modules.content.models import (
    AssetCategory,
    Content,
    ContentAsset,
    ContentStatus,
)
from app.modules.exports.models import ManagedObject, ManagedObjectState
from app.modules.generation.cover_models import (
    CoverMode,
    CoverReference,
    CoverRequest,
    CoverSize,
    ReferencePurpose,
)
from app.modules.generation.cover_service import (
    CoverGenerationCoordinator,
    CoverIdempotencyConflict,
    CoverSafetyResult,
)
from app.modules.generation.models import (
    CoverArtifactAttempt,
    CoverAttemptStatus,
    CoverGenerationRun,
    CoverGenerationStatus,
)
from app.modules.metrics.models import ContentType
from app.modules.models.adapters.qianwen import (
    ModelErrorCode,
    ModelProviderError,
)
from app.modules.models.capabilities import AdapterStatus, Capability
from app.modules.models.catalog import QIANWEN_IMAGE_MODEL_ID, QianwenRegion
from app.modules.models.config_service import (
    ModelConfigService,
    SecretCipher,
    model_configuration_version,
)
from app.modules.imports.ocr_adapters import VisionRecognition
from app.modules.risk_rag.models import RiskScan
from app.modules.workspace.models import MemberRole, Workspace, WorkspaceMember
from app.modules.workspace.permissions import PermissionDenied


NOW = datetime(2026, 7, 29, 9, tzinfo=UTC)


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.fail_put_after: int | None = None
        self.put_count = 0

    def put_object(
        self,
        object_key: str,
        content: bytes,
        *,
        mime_type: str,
    ) -> None:
        self.put_count += 1
        if (
            self.fail_put_after is not None
            and self.put_count > self.fail_put_after
        ):
            raise RuntimeError("synthetic object write failure")
        self.objects[object_key] = (content, mime_type)

    def get_object(self, object_key: str) -> bytes:
        try:
            return self.objects[object_key][0]
        except KeyError as error:
            raise FileNotFoundError(object_key) from error

    def inspect_object(self, object_key: str) -> StoredObject | None:
        item = self.objects.get(object_key)
        if item is None:
            return None
        return StoredObject(size=len(item[0]), mime_type=item[1])

    def delete_object(self, object_key: str) -> None:
        self.objects.pop(object_key, None)

    def presign_download(self, object_key: str):
        raise AssertionError("cover worker must not create public URLs")

    def issue_upload(self, **metadata):
        raise AssertionError("cover worker uses server-side object writes")

    def verify_upload_token(self, token: str):
        raise AssertionError("cover worker does not accept upload tokens")


class RecordingAdapter:
    capabilities = frozenset({Capability.IMAGE})
    status = AdapterStatus.EXPERIMENTAL

    def __init__(
        self,
        *,
        active_sessions,
        failure: ModelProviderError | None = None,
    ) -> None:
        self.active_sessions = active_sessions
        self.failure = failure
        self.calls = 0
        self.requests = []
        self.prepared_images = ()
        self.last_metadata = type(
            "Metadata",
            (),
            {
                "provider_request_id": "synthetic-provider-request",
                "seed": 29,
                "width": 512,
                "height": 512,
            },
        )()

    async def generate_layer(self, request):
        assert self.active_sessions() == 0
        self.calls += 1
        self.requests.append(request)
        if self.failure is not None:
            raise self.failure
        return Image.new("RGB", (512, 512), "#245789")


class RecordingSafetyGate:
    def __init__(
        self,
        *,
        high_risk: bool = False,
        low_confidence: bool = False,
    ) -> None:
        self.high_risk = high_risk
        self.low_confidence = low_confidence
        self.calls = 0

    def scan(self, *, png_bytes, workspace_id, platform, content_id):
        self.calls += 1
        assert png_bytes.startswith(b"\x89PNG")
        return CoverSafetyResult(
            ocr_model_version="mock-ocr-cover-v1",
            ocr_confidence=0.41 if self.low_confidence else 0.99,
            risk_scan_id=uuid4(),
            risk_rule_version="risk-cover-v1",
            high_risk=self.high_risk,
            requires_human_review=self.low_confidence or self.high_risk,
            disclaimer="辅助判断，不保证通过平台审核",
        )


def _png(color: str = "#345678") -> bytes:
    output = BytesIO()
    Image.new("RGB", (512, 512), color).save(output, "PNG")
    return output.getvalue()


@pytest.fixture
def environment():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    storage = MemoryStorage()
    active = 0

    class TrackedSession(Session):
        def __enter__(self):
            nonlocal active
            active += 1
            return super().__enter__()

        def __exit__(self, *args):
            nonlocal active
            try:
                return super().__exit__(*args)
            finally:
                active -= 1

    tracked_factory = sessionmaker(
        bind=engine,
        class_=TrackedSession,
        expire_on_commit=False,
    )
    with factory() as session, session.begin():
        workspace = Workspace(name="合成封面工作区")
        other_workspace = Workspace(name="其他合成工作区")
        session.add_all([workspace, other_workspace])
        session.flush()
        admin = WorkspaceMember(
            workspace_id=workspace.id,
            display_name="合成管理员",
            role=MemberRole.ADMIN,
        )
        editor = WorkspaceMember(
            workspace_id=workspace.id,
            display_name="合成编辑",
            role=MemberRole.EDITOR,
        )
        viewer = WorkspaceMember(
            workspace_id=workspace.id,
            display_name="合成查看者",
            role=MemberRole.VIEWER,
        )
        session.add_all([admin, editor, viewer])
        session.flush()
        account = PlatformAccount(
            workspace_id=workspace.id,
            platform=Platform.XIAOHONGSHU,
            name="合成账号",
        )
        other_account = PlatformAccount(
            workspace_id=other_workspace.id,
            platform=Platform.XIAOHONGSHU,
            name="其他账号",
        )
        session.add_all([account, other_account])
        session.flush()
        objective = ObjectiveProfile(
            workspace_id=workspace.id,
            account_id=account.id,
            version=1,
            objectives=["synthetic"],
            metric_weights={},
        )
        benchmark = BenchmarkProfile(
            workspace_id=workspace.id,
            account_id=account.id,
            version=1,
            sample_size=0,
        )
        other_objective = ObjectiveProfile(
            workspace_id=other_workspace.id,
            account_id=other_account.id,
            version=1,
            objectives=["synthetic"],
            metric_weights={},
        )
        other_benchmark = BenchmarkProfile(
            workspace_id=other_workspace.id,
            account_id=other_account.id,
            version=1,
            sample_size=0,
        )
        session.add_all(
            [objective, benchmark, other_objective, other_benchmark]
        )
        session.flush()
        content = Content(
            workspace_id=workspace.id,
            account_id=account.id,
            platform=Platform.XIAOHONGSHU,
            title="人工合成内容",
            body="人工合成正文",
            objective_profile_id=objective.id,
            benchmark_profile_id=benchmark.id,
            content_type=ContentType.IMAGE_TEXT,
            status=ContentStatus.DRAFT,
        )
        other_content = Content(
            workspace_id=other_workspace.id,
            account_id=other_account.id,
            platform=Platform.XIAOHONGSHU,
            title="其他工作区内容",
            body="其他工作区正文",
            objective_profile_id=other_objective.id,
            benchmark_profile_id=other_benchmark.id,
            content_type=ContentType.IMAGE_TEXT,
            status=ContentStatus.DRAFT,
        )
        session.add_all([content, other_content])
        session.flush()
        reference = ContentAsset(
            workspace_id=workspace.id,
            content_id=content.id,
            category=AssetCategory.REFERENCE_IMAGE,
            object_key=(
                f"workspaces/{workspace.id}/contents/{content.id}/"
                "synthetic-reference.png"
            ),
            file_name="synthetic-reference.png",
            mime_type="image/png",
            size=len(_png()),
        )
        logo = ContentAsset(
            workspace_id=workspace.id,
            content_id=content.id,
            category=AssetCategory.REFERENCE_IMAGE,
            object_key=(
                f"workspaces/{workspace.id}/contents/{content.id}/"
                "synthetic-logo.png"
            ),
            file_name="synthetic-logo.png",
            mime_type="image/png",
            size=len(_png("#ff3366")),
        )
        foreign_reference = ContentAsset(
            workspace_id=other_workspace.id,
            content_id=other_content.id,
            category=AssetCategory.REFERENCE_IMAGE,
            object_key=(
                f"workspaces/{other_workspace.id}/contents/"
                f"{other_content.id}/foreign.png"
            ),
            file_name="foreign.png",
            mime_type="image/png",
            size=len(_png()),
        )
        session.add_all([reference, logo, foreign_reference])
        session.flush()
        storage.objects[reference.object_key] = (_png(), "image/png")
        storage.objects[logo.object_key] = (_png("#ff3366"), "image/png")
        storage.objects[foreign_reference.object_key] = (
            _png(),
            "image/png",
        )
        cipher = SecretCipher("synthetic-cover-encryption-key")
        config = ModelConfigService(
            session,
            WorkspaceContext(
                workspace_id=workspace.id,
                member_id=admin.id,
                role="admin",
            ),
            cipher=cipher,
        ).save(
            provider="qianwen",
            model_id=QIANWEN_IMAGE_MODEL_ID,
            capabilities=frozenset({Capability.IMAGE}),
            status=AdapterStatus.EXPERIMENTAL,
            api_key="sk-synthetic-cover-never-real",
            region=QianwenRegion.CN_BEIJING,
            provider_workspace_id="llm-cover1234",
        )
        values = {
            "workspace": workspace,
            "other_workspace": other_workspace,
            "admin": admin,
            "editor": editor,
            "viewer": viewer,
            "account": account,
            "content": content,
            "reference": reference,
            "logo": logo,
            "foreign_reference": foreign_reference,
            "config": config,
            "cipher": cipher,
        }
    yield factory, tracked_factory, storage, values, lambda: active


def _context(values, role: str = "editor") -> WorkspaceContext:
    member = values[role]
    return WorkspaceContext(
        workspace_id=values["workspace"].id,
        member_id=member.id,
        role=role,
    )


def _request(
    values,
    *,
    mode: CoverMode = CoverMode.AI_VISUAL,
    reference_id: UUID | None = None,
    logo: bool = False,
    prompt: str = "人工合成蓝色产品背景",
) -> CoverRequest:
    references = (
        (
            CoverReference(
                asset_id=reference_id or values["reference"].id,
                purpose=ReferencePurpose.PRODUCT,
                provider_input=True,
            ),
        )
        if reference_id is not None or mode is CoverMode.HYBRID
        else ()
    )
    return CoverRequest(
        mode=mode,
        size=CoverSize(width=512, height=512),
        prompt=prompt,
        headline="程序化中文标题",
        subtitle="程序化副标题",
        references=references,
        preserve_product=mode is CoverMode.HYBRID,
        model_config_id=(
            None if mode is CoverMode.TEMPLATE else values["config"].id
        ),
        brand_name="合成品牌",
        logo_asset_id=values["logo"].id if logo else None,
        image_parameters=(
            {"seed": 29} if mode is CoverMode.CUSTOM else {}
        ),
    )


def _coordinator(
    tracked_factory,
    values,
    *,
    role: str = "editor",
    publish_hook=None,
):
    return CoverGenerationCoordinator(
        tracked_factory,
        context=_context(values, role),
        clock=lambda: NOW,
        publish_hook=publish_hook,
    )


def test_create_is_idempotent_and_conflicting_fingerprint_is_rejected(
    environment,
) -> None:
    _, tracked, _, values, _ = environment
    coordinator = _coordinator(tracked, values)
    request = _request(values)

    first = coordinator.request(
        content_id=values["content"].id,
        request=request,
        idempotency_key="cover-1",
    )
    second = coordinator.request(
        content_id=values["content"].id,
        request=request,
        idempotency_key="cover-1",
    )

    assert second == first
    with pytest.raises(CoverIdempotencyConflict):
        coordinator.request(
            content_id=values["content"].id,
            request=_request(values, prompt="不同的人工合成提示"),
            idempotency_key="cover-1",
        )


def test_permissions_cross_workspace_and_demo_billing_are_denied(
    environment,
) -> None:
    _, tracked, _, values, _ = environment

    with pytest.raises(PermissionDenied):
        _coordinator(tracked, values, role="viewer").request(
            content_id=values["content"].id,
            request=_request(values),
            idempotency_key="viewer-cover",
        )
    with pytest.raises(LookupError):
        _coordinator(tracked, values).request(
            content_id=uuid4(),
            request=_request(values),
            idempotency_key="foreign-cover",
        )
    demo_context = WorkspaceContext(
        workspace_id=values["workspace"].id,
        member_id=None,
        role="demo",
    )
    demo = CoverGenerationCoordinator(
        tracked,
        context=demo_context,
        clock=lambda: NOW,
    )
    with pytest.raises(PermissionDenied):
        demo.request(
            content_id=values["content"].id,
            request=_request(values),
            idempotency_key="demo-paid-cover",
        )


def test_provider_runs_without_database_session_and_persists_provenance(
    environment,
) -> None:
    factory, tracked, storage, values, active_sessions = environment
    coordinator = _coordinator(tracked, values)
    request = _request(
        values,
        mode=CoverMode.HYBRID,
        reference_id=values["reference"].id,
        logo=True,
    )
    run_id = coordinator.request(
        content_id=values["content"].id,
        request=request,
        idempotency_key="successful-cover",
    )
    adapter = RecordingAdapter(active_sessions=active_sessions)
    gate = RecordingSafetyGate()

    coordinator.run(
        run_id,
        adapter=adapter,
        storage=storage,
        safety_gate=gate,
    )

    assert adapter.calls == 1
    assert tuple(
        item.asset_id for item in adapter.prepared_images
    ) == (values["reference"].id,)
    assert values["logo"].id not in {
        item.asset_id for item in adapter.prepared_images
    }
    with factory() as session:
        run = session.get(CoverGenerationRun, run_id)
        attempt = session.scalar(
            select(CoverArtifactAttempt).where(
                CoverArtifactAttempt.run_id == run_id
            )
        )
        assert run is not None
        assert attempt is not None
        assert run.status is CoverGenerationStatus.SUCCEEDED
        assert attempt.status is CoverAttemptStatus.SUCCEEDED
        assert attempt.provider == "qianwen"
        assert attempt.model_id == QIANWEN_IMAGE_MODEL_ID
        assert attempt.contract_version.endswith("cover-layer-v1")
        assert attempt.model_config_id == values["config"].id
        assert attempt.request_fingerprint == run.request_fingerprint
        assert attempt.prompt_hash == hashlib.sha256(
            request.prompt.encode()
        ).hexdigest()
        assert attempt.seed is None
        assert attempt.provider_request_id == "synthetic-provider-request"
        assert attempt.output_sha256 is not None
        assert attempt.output_mime_type == "image/png"
        assert attempt.output_width == 512
        assert attempt.output_height == 512
        assert attempt.layout_version == "cover-layout-v1"
        assert attempt.ocr_model_version == "mock-ocr-cover-v1"
        assert attempt.risk_scan_id is not None
        assert attempt.publish_eligible is True
        assert attempt.input_assets == [
            {
                "asset_id": str(values["reference"].id),
                "asset_version": values["reference"].updated_at.isoformat(),
                "sha256": hashlib.sha256(
                    storage.objects[values["reference"].object_key][0]
                ).hexdigest(),
                "purpose": "product",
                "order": 1,
            }
        ]
        assert attempt.output_object_key in storage.objects
        assert "signed" not in str(attempt.input_assets)
        assert request.prompt not in str(attempt.input_assets)
        managed = session.scalar(
            select(ManagedObject).where(
                ManagedObject.object_key == attempt.output_object_key
            )
        )
        assert managed is not None
        assert managed.state is ManagedObjectState.REFERENCED


def test_template_mode_never_calls_provider(environment) -> None:
    factory, tracked, storage, values, active_sessions = environment
    coordinator = _coordinator(tracked, values)
    run_id = coordinator.request(
        content_id=values["content"].id,
        request=_request(values, mode=CoverMode.TEMPLATE),
        idempotency_key="template-cover",
    )
    adapter = RecordingAdapter(active_sessions=active_sessions)

    coordinator.run(
        run_id,
        adapter=adapter,
        storage=storage,
        safety_gate=RecordingSafetyGate(),
    )

    assert adapter.calls == 0
    with factory() as session:
        attempt = session.scalar(
            select(CoverArtifactAttempt).where(
                CoverArtifactAttempt.run_id == run_id
            )
        )
        assert attempt is not None
        assert attempt.provider == "template"
        assert attempt.billed_attempt_status == "not_billed"


def test_reference_change_or_cleanup_state_stops_before_provider(
    environment,
) -> None:
    factory, tracked, storage, values, active_sessions = environment
    coordinator = _coordinator(tracked, values)
    run_id = coordinator.request(
        content_id=values["content"].id,
        request=_request(
            values,
            mode=CoverMode.HYBRID,
            reference_id=values["reference"].id,
        ),
        idempotency_key="changed-reference",
    )
    with factory() as session, session.begin():
        session.add(
            ManagedObject(
                workspace_id=values["workspace"].id,
                owner_type="synthetic_reference",
                owner_id=values["reference"].id,
                managed_prefix=f"workspaces/{values['workspace'].id}/",
                policy_version=0,
                strategy="scheduled",
                state=ManagedObjectState.RETRYING,
                object_key=values["reference"].object_key,
                purge_at=NOW,
            )
        )
    adapter = RecordingAdapter(active_sessions=active_sessions)

    with pytest.raises(RuntimeError, match="reference"):
        coordinator.run(
            run_id,
            adapter=adapter,
            storage=storage,
            safety_gate=RecordingSafetyGate(),
        )

    assert adapter.calls == 0
    with factory() as session:
        run = session.get(CoverGenerationRun, run_id)
        assert run is not None
        assert run.status is CoverGenerationStatus.FAILED
        assert run.error_code == "COVER_GENERATION_FAILED"


def test_unknown_provider_outcome_requires_new_manual_attempt(
    environment,
) -> None:
    factory, tracked, storage, values, active_sessions = environment
    coordinator = _coordinator(tracked, values)
    run_id = coordinator.request(
        content_id=values["content"].id,
        request=_request(values),
        idempotency_key="unknown-outcome",
    )
    failed = RecordingAdapter(
        active_sessions=active_sessions,
        failure=ModelProviderError(
            ModelErrorCode.PROVIDER_OUTCOME_UNKNOWN
        ),
    )

    with pytest.raises(ModelProviderError):
        coordinator.run(
            run_id,
            adapter=failed,
            storage=storage,
            safety_gate=RecordingSafetyGate(),
        )

    assert failed.calls == 1
    with factory() as session:
        run = session.get(CoverGenerationRun, run_id)
        first = session.scalar(
            select(CoverArtifactAttempt).where(
                CoverArtifactAttempt.run_id == run_id
            )
        )
        assert run is not None
        assert first is not None
        assert run.status is CoverGenerationStatus.PROVIDER_OUTCOME_UNKNOWN
        assert first.status is CoverAttemptStatus.PROVIDER_OUTCOME_UNKNOWN
        assert first.billed_attempt_status == "outcome_unknown"

    retry_id = coordinator.retry(
        run_id,
        idempotency_key="manual-retry-1",
    )
    assert retry_id == run_id
    success = RecordingAdapter(active_sessions=active_sessions)
    coordinator.run(
        run_id,
        adapter=success,
        storage=storage,
        safety_gate=RecordingSafetyGate(),
    )
    with factory() as session:
        attempts = list(
            session.scalars(
                select(CoverArtifactAttempt)
                .where(CoverArtifactAttempt.run_id == run_id)
                .order_by(CoverArtifactAttempt.attempt_number)
            )
        )
        assert [item.attempt_number for item in attempts] == [1, 2]
        assert attempts[1].previous_attempt_id == attempts[0].id


def test_cancelled_or_stale_worker_cannot_publish(environment) -> None:
    factory, tracked, storage, values, active_sessions = environment
    holder: dict[str, object] = {}

    def cancel_before_publish() -> None:
        holder["coordinator"].cancel(holder["run_id"])

    coordinator = _coordinator(
        tracked,
        values,
        publish_hook=cancel_before_publish,
    )
    run_id = coordinator.request(
        content_id=values["content"].id,
        request=_request(values),
        idempotency_key="cancel-race",
    )
    holder.update(coordinator=coordinator, run_id=run_id)

    with pytest.raises(RuntimeError, match="claim"):
        coordinator.run(
            run_id,
            adapter=RecordingAdapter(active_sessions=active_sessions),
            storage=storage,
            safety_gate=RecordingSafetyGate(),
        )

    with factory() as session:
        run = session.get(CoverGenerationRun, run_id)
        assert run is not None
        assert run.status is CoverGenerationStatus.CANCELLED
        assert session.scalar(
            select(CoverArtifactAttempt).where(
                CoverArtifactAttempt.run_id == run_id,
                CoverArtifactAttempt.status == CoverAttemptStatus.SUCCEEDED,
            )
        ) is None
        managed = list(
            session.scalars(
                select(ManagedObject).where(
                    ManagedObject.owner_type == "cover_generation_attempt",
                )
            )
        )
        assert managed
        assert all(
            item.state is ManagedObjectState.SCHEDULED
            and item.purge_at == NOW
            for item in managed
        )


@pytest.mark.parametrize(
    ("high_risk", "low_confidence", "publish_eligible"),
    [(True, False, False), (False, True, False)],
)
def test_ocr_and_risk_gate_require_review_before_publication(
    environment,
    high_risk: bool,
    low_confidence: bool,
    publish_eligible: bool,
) -> None:
    factory, tracked, storage, values, active_sessions = environment
    coordinator = _coordinator(tracked, values)
    run_id = coordinator.request(
        content_id=values["content"].id,
        request=_request(values),
        idempotency_key=f"gate-{high_risk}-{low_confidence}",
    )

    coordinator.run(
        run_id,
        adapter=RecordingAdapter(active_sessions=active_sessions),
        storage=storage,
        safety_gate=RecordingSafetyGate(
            high_risk=high_risk,
            low_confidence=low_confidence,
        ),
    )

    with factory() as session:
        attempt = session.scalar(
            select(CoverArtifactAttempt).where(
                CoverArtifactAttempt.run_id == run_id
            )
        )
        assert attempt is not None
        assert attempt.requires_human_review is True
        assert attempt.publish_eligible is publish_eligible
        assert attempt.disclaimer == "辅助判断，不保证通过平台审核"


def test_database_publish_failure_registers_orphan_for_compensation(
    environment,
) -> None:
    factory, tracked, storage, values, active_sessions = environment

    def fail_publish() -> None:
        raise RuntimeError("synthetic database publish failure")

    coordinator = _coordinator(
        tracked,
        values,
        publish_hook=fail_publish,
    )
    run_id = coordinator.request(
        content_id=values["content"].id,
        request=_request(values),
        idempotency_key="compensation",
    )

    with pytest.raises(RuntimeError, match="publish"):
        coordinator.run(
            run_id,
            adapter=RecordingAdapter(active_sessions=active_sessions),
            storage=storage,
            safety_gate=RecordingSafetyGate(),
        )

    with factory() as session:
        run = session.get(CoverGenerationRun, run_id)
        managed = list(
            session.scalars(
                select(ManagedObject).where(
                    ManagedObject.workspace_id == values["workspace"].id,
                    ManagedObject.owner_type == "cover_generation_attempt",
                )
            )
        )
        assert run is not None
        assert run.status is CoverGenerationStatus.COMPENSATION_REQUIRED
        assert any(
            item.state
            in {ManagedObjectState.ACTIVE, ManagedObjectState.RETRYING}
            and item.object_key in storage.objects
            for item in managed
        )


def test_object_write_failure_never_marks_success(environment) -> None:
    factory, tracked, storage, values, active_sessions = environment
    storage.fail_put_after = 1
    coordinator = _coordinator(tracked, values)
    run_id = coordinator.request(
        content_id=values["content"].id,
        request=_request(values),
        idempotency_key="object-failure",
    )

    with pytest.raises(RuntimeError, match="object"):
        coordinator.run(
            run_id,
            adapter=RecordingAdapter(active_sessions=active_sessions),
            storage=storage,
            safety_gate=RecordingSafetyGate(),
        )

    with factory() as session:
        run = session.get(CoverGenerationRun, run_id)
        attempt = session.scalar(
            select(CoverArtifactAttempt).where(
                CoverArtifactAttempt.run_id == run_id
            )
        )
        assert run is not None
        assert attempt is not None
        assert run.status is not CoverGenerationStatus.SUCCEEDED
        assert run.error_code == "COVER_OBJECT_WRITE_FAILED"
        assert attempt.provider_request_id == "synthetic-provider-request"
        assert attempt.provider_completed_at == NOW
        assert attempt.billed_attempt_status == "completed"


def test_cover_worker_adapter_is_bound_to_frozen_config_and_never_retries(
    environment,
) -> None:
    from app.modules.generation.tasks import (
        build_cover_adapter_for_run,
        generate_cover_task,
    )
    from app.modules.models.adapters.qianwen_image import (
        QianwenCoverImageAdapter,
    )

    factory, _, _, values, _ = environment
    with factory() as session:
        run = CoverGenerationRun(
            workspace_id=values["workspace"].id,
            requested_by=values["editor"].id,
            account_id=values["account"].id,
            content_id=values["content"].id,
            platform="xiaohongshu",
            provider="qianwen",
            model_id=QIANWEN_IMAGE_MODEL_ID,
            contract_version=(
                "qianwen-image-2.0-pro-2026-06-22-cover-layer-v1"
            ),
            configuration_version=model_configuration_version(
                values["config"]
            ),
            cover_mode="ai_visual",
            request_json={},
            request_fingerprint="a" * 64,
            idempotency_key="worker-binding",
            status=CoverGenerationStatus.QUEUED,
            model_config_id=values["config"].id,
            region="cn-beijing",
        )
        adapter = build_cover_adapter_for_run(
            session=session,
            run=run,
            cipher=values["cipher"],
            mock_mode=False,
        )

    assert isinstance(adapter, QianwenCoverImageAdapter)
    assert not getattr(generate_cover_task, "autoretry_for", ())


def test_default_cover_safety_gate_persists_fail_closed_risk_scan(
    environment,
) -> None:
    from app.modules.generation.cover_safety import PersistedCoverSafetyGate

    factory, tracked, _, values, _ = environment
    result = PersistedCoverSafetyGate(
        tracked,
        context=_context(values),
        account_id=values["account"].id,
        title="人工合成标题",
        body="人工合成正文",
        now=lambda: NOW,
    ).scan(
        png_bytes=_png(),
        workspace_id=values["workspace"].id,
        platform="xiaohongshu",
        content_id=values["content"].id,
    )

    assert result.requires_human_review is True
    assert result.ocr_confidence == 0
    with factory() as session:
        scan = session.get(RiskScan, result.risk_scan_id)
        assert scan is not None
        assert scan.workspace_id == values["workspace"].id
        assert scan.ocr_provider == "unavailable"


def test_repeated_cover_bytes_create_distinct_immutable_scan_history(
    environment,
) -> None:
    from app.modules.generation.cover_safety import PersistedCoverSafetyGate

    factory, tracked, _, values, _ = environment
    first = PersistedCoverSafetyGate(
        tracked,
        context=_context(values),
        account_id=values["account"].id,
        title="人工合成标题",
        body="人工合成正文",
        now=lambda: NOW,
    ).scan(
        png_bytes=_png(),
        workspace_id=values["workspace"].id,
        platform="xiaohongshu",
        content_id=values["content"].id,
    )
    second = PersistedCoverSafetyGate(
        tracked,
        context=_context(values),
        account_id=values["account"].id,
        title="人工合成标题",
        body="人工合成正文",
        now=lambda: NOW + timedelta(seconds=1),
    ).scan(
        png_bytes=_png(),
        workspace_id=values["workspace"].id,
        platform="xiaohongshu",
        content_id=values["content"].id,
    )

    assert second.risk_scan_id != first.risk_scan_id
    with factory() as session:
        assert session.query(RiskScan).count() == 2


def test_cover_safety_gate_executes_bound_ocr_before_risk_scan(
    environment,
) -> None:
    from app.modules.generation.cover_safety import PersistedCoverSafetyGate

    class SyntheticOcr:
        calls = 0

        def recognize(self, image: bytes, mime_type: str) -> VisionRecognition:
            self.calls += 1
            assert image.startswith(b"\x89PNG")
            assert mime_type == "image/png"
            return VisionRecognition.model_validate(
                {
                    "platform": "xiaohongshu",
                    "platform_confidence": 0,
                    "metric_candidates": [],
                    "text_regions": [
                        {
                            "text": "人工合成标题",
                            "region": {
                                "x": 0.1,
                                "y": 0.1,
                                "width": 0.5,
                                "height": 0.1,
                            },
                        }
                    ],
                    "confidence_source": "unavailable",
                    "requires_human_review": True,
                    "model_id": "qwen-vl-ocr-2025-11-20",
                    "contract_version": "qwen-ocr-advanced-v1",
                }
            )

    factory, tracked, _, values, _ = environment
    ocr = SyntheticOcr()
    result = PersistedCoverSafetyGate(
        tracked,
        context=_context(values),
        account_id=values["account"].id,
        title="人工合成标题",
        body="人工合成正文",
        vision_adapter=ocr,
        now=lambda: NOW,
    ).scan(
        png_bytes=_png(),
        workspace_id=values["workspace"].id,
        platform="xiaohongshu",
        content_id=values["content"].id,
    )

    assert ocr.calls == 1
    assert result.ocr_model_version == "qwen-vl-ocr-2025-11-20"
    assert result.requires_human_review is True
    with factory() as session:
        scan = session.get(RiskScan, result.risk_scan_id)
        assert scan is not None
        assert scan.ocr_provider == "qianwen"
        assert scan.ocr_model_id == "qwen-vl-ocr-2025-11-20"
