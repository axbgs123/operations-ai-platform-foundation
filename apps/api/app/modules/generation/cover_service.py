import hashlib
import json
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Protocol
from uuid import UUID

from PIL import Image, ImageDraw
from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import WorkspaceContext
from app.core.storage import Storage
from app.modules.content.models import Content, ContentAsset
from app.modules.exports.deletion import RetentionService
from app.modules.exports.models import ManagedObject, ManagedObjectState
from app.modules.generation.cover_models import (
    CoverMode,
    CoverReference,
    CoverRequest,
    CoverSize,
    ReferencePurpose,
)
from app.modules.generation.models import (
    CoverArtifactAttempt,
    CoverAttemptStatus,
    CoverGenerationRun,
    CoverGenerationStatus,
)
from app.modules.generation.layout import (
    CoverLayout,
    compute_cover_layout,
    render_cover,
)
from app.modules.models.capabilities import (
    AdapterStatus,
    Capability,
    IncompatibleModelError,
)
from app.modules.models.adapters.qianwen import (
    ModelProviderError,
    safe_model_error_message,
)
from app.modules.models.catalog import get_catalog_entry
from app.modules.models.config_service import model_configuration_version
from app.modules.models.models import ModelConfig, ModelConfigStatus
from app.modules.workspace.permissions import Permission, require_permission


IMAGE_LAYER_POLICY = (
    "Only generate background and subject pixels. "
    "Do not render text, letters, numbers, logos, brand marks, or watermarks. "
    "Keep clean negative space for the programmatic title area."
)


class ImageModelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy: str
    prompt: str
    size: CoverSize
    references: tuple[CoverReference, ...]
    locked_reference_ids: tuple[UUID, ...]
    allow_text: bool = False
    output_layers: tuple[str, ...] = ("background", "subject")
    parameters: dict[str, JsonValue] = Field(default_factory=dict)


class CoverPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: CoverMode
    prompt: str
    references: tuple[CoverReference, ...]
    uses_image_model: bool
    model_request: ImageModelRequest | None
    overlay_text: tuple[str, str]


class CoverImageAdapter(Protocol):
    capabilities: frozenset[Capability]
    status: AdapterStatus

    async def generate_layer(
        self,
        request: ImageModelRequest,
    ) -> Image.Image: ...


class CoverSafetyResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ocr_model_version: str
    ocr_confidence: float = Field(ge=0, le=1)
    risk_scan_id: UUID
    risk_rule_version: str
    high_risk: bool
    requires_human_review: bool
    disclaimer: str = "辅助判断，不保证通过平台审核"


class CoverSafetyGate(Protocol):
    def scan(
        self,
        *,
        png_bytes: bytes,
        workspace_id: UUID,
        platform: str,
        content_id: UUID,
    ) -> CoverSafetyResult: ...


class MockCoverImageAdapter:
    capabilities = frozenset({Capability.IMAGE})
    status = AdapterStatus.VERIFIED

    async def generate_layer(
        self,
        request: ImageModelRequest,
    ) -> Image.Image:
        digest = hashlib.sha256(request.model_dump_json().encode()).hexdigest()
        first = f"#{digest[:6]}"
        second = f"#{digest[6:12]}"
        image = Image.new(
            "RGB",
            (request.size.width, request.size.height),
            first,
        )
        draw = ImageDraw.Draw(image)
        draw.ellipse(
            (
                request.size.width // 5,
                request.size.height // 4,
                request.size.width,
                request.size.height,
            ),
            fill=second,
        )
        return image


@dataclass(frozen=True)
class CoverArtifact:
    png_bytes: bytes
    text_content: tuple[str, str, str]
    layout: CoverLayout
    mode: CoverMode
    logo_composited: bool


class CoverIdempotencyConflict(ValueError):
    pass


def build_cover_plan(request: CoverRequest) -> CoverPlan:
    uses_image_model = request.mode is not CoverMode.TEMPLATE
    locked_purposes: set[ReferencePurpose] = set()
    if request.preserve_person:
        locked_purposes.add(ReferencePurpose.PERSON)
    if request.preserve_product:
        locked_purposes.add(ReferencePurpose.PRODUCT)
    model_request = (
        ImageModelRequest(
            policy=IMAGE_LAYER_POLICY,
            prompt=request.prompt,
            size=request.size,
            references=tuple(
                reference
                for reference in request.references
                if reference.provider_input
            ),
            locked_reference_ids=tuple(
                reference.asset_id
                for reference in request.references
                if reference.provider_input
                and reference.purpose in locked_purposes
            ),
            parameters=request.image_parameters,
        )
        if uses_image_model
        else None
    )
    return CoverPlan(
        mode=request.mode,
        prompt=request.prompt,
        references=request.references,
        uses_image_model=uses_image_model,
        model_request=model_request,
        overlay_text=(request.headline, request.subtitle),
    )


def _template_base(
    request: CoverRequest,
    asset_images: Mapping[UUID, Image.Image],
) -> Image.Image:
    composition = next(
        (
            asset_images[reference.asset_id]
            for reference in request.references
            if reference.purpose is ReferencePurpose.COMPOSITION
            and reference.asset_id in asset_images
        ),
        None,
    )
    if composition is not None:
        return composition
    image = Image.new(
        "RGB",
        (request.size.width, request.size.height),
        "#102a43",
    )
    draw = ImageDraw.Draw(image)
    draw.rectangle(
        (
            0,
            request.size.height * 2 // 3,
            request.size.width,
            request.size.height,
        ),
        fill="#0b7285",
    )
    return image


async def generate_cover(
    request: CoverRequest,
    *,
    adapter: CoverImageAdapter | None = None,
    asset_images: Mapping[UUID, Image.Image] | None = None,
) -> CoverArtifact:
    images = asset_images or {}
    plan = build_cover_plan(request)
    if plan.model_request is None:
        base = _template_base(request, images)
    else:
        selected_adapter = adapter or MockCoverImageAdapter()
        if (
            selected_adapter.status is AdapterStatus.INCOMPATIBLE
            or Capability.IMAGE not in selected_adapter.capabilities
        ):
            raise IncompatibleModelError("cover adapter requires image capability")
        base = await selected_adapter.generate_layer(plan.model_request)
    return compose_cover(
        request,
        base=base,
        asset_images=images,
    )


def compose_cover(
    request: CoverRequest,
    *,
    base: Image.Image,
    asset_images: Mapping[UUID, Image.Image] | None = None,
) -> CoverArtifact:
    images = asset_images or {}
    logo = (
        images.get(request.logo_asset_id) if request.logo_asset_id is not None else None
    )
    if request.logo_asset_id is not None and logo is None:
        raise ValueError("selected logo asset is unavailable")
    layout = compute_cover_layout(
        size=request.size,
        headline=request.headline,
        subtitle=request.subtitle,
        brand_name=request.brand_name,
        safe_area=request.safe_area,
        logo_size=logo.size if logo is not None else None,
    )
    rendered = render_cover(base, layout, logo=logo)
    return CoverArtifact(
        png_bytes=rendered.png_bytes,
        text_content=rendered.text_content,
        layout=layout,
        mode=request.mode,
        logo_composited=logo is not None,
    )


@dataclass(frozen=True)
class _FrozenAsset:
    id: UUID
    version: str
    object_key: str
    mime_type: str
    size: int
    purpose: ReferencePurpose | None
    provider_input: bool
    is_logo: bool


@dataclass(frozen=True)
class _FrozenCover:
    run_id: UUID
    attempt_id: UUID
    claim_token: str
    operation_version: int
    workspace_id: UUID
    content_id: UUID
    platform: str
    request: CoverRequest
    assets: tuple[_FrozenAsset, ...]
    provider: str
    model_id: str
    region: str | None
    model_config_id: UUID | None
    configuration_version: str
    contract_version: str
    attempt_number: int


SessionFactory = Callable[[], Session]
Clock = Callable[[], datetime]
PublishHook = Callable[[], None]


class CoverGenerationCoordinator:
    """Fenced cover generation with Provider I/O outside DB transactions."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        context: WorkspaceContext,
        clock: Clock = lambda: datetime.now(UTC),
        publish_hook: PublishHook | None = None,
        lease_seconds: int = 900,
    ) -> None:
        self._session_factory = session_factory
        self._context = context
        self._clock = clock
        self._publish_hook = publish_hook
        self._lease_seconds = lease_seconds

    def request(
        self,
        *,
        content_id: UUID,
        request: CoverRequest,
        idempotency_key: str,
    ) -> UUID:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        if self._context.member_id is None:
            raise PermissionError("cover generation requires a workspace member")
        if not idempotency_key.strip() or len(idempotency_key) > 200:
            raise ValueError("invalid cover idempotency key")
        fingerprint = self._fingerprint(content_id, request)
        with self._session_factory() as session, session.begin():
            existing = session.scalar(
                select(CoverGenerationRun).where(
                    CoverGenerationRun.workspace_id
                    == self._context.workspace_id,
                    CoverGenerationRun.requested_by
                    == self._context.member_id,
                    CoverGenerationRun.idempotency_key
                    == idempotency_key,
                )
            )
            if existing is not None:
                if existing.request_fingerprint != fingerprint:
                    raise CoverIdempotencyConflict(
                        "cover idempotency key conflicts with another request"
                    )
                return existing.id
            content = session.scalar(
                select(Content).where(
                    Content.id == content_id,
                    Content.workspace_id == self._context.workspace_id,
                    Content.deleted_at.is_(None),
                )
            )
            if content is None:
                raise LookupError("content not found")
            (
                provider,
                model_id,
                region,
                config_id,
                config_version,
                contract_version,
            ) = self._binding(session, request)
            self._validate_assets(
                session,
                content=content,
                request=request,
            )
            run = CoverGenerationRun(
                workspace_id=self._context.workspace_id,
                requested_by=self._context.member_id,
                account_id=content.account_id,
                content_id=content.id,
                platform=content.platform.value,
                model_config_id=config_id,
                provider=provider,
                model_id=model_id,
                region=region,
                contract_version=contract_version,
                configuration_version=config_version,
                cover_mode=request.mode.value,
                request_json=request.model_dump(mode="json"),
                request_fingerprint=fingerprint,
                idempotency_key=idempotency_key,
                status=CoverGenerationStatus.QUEUED,
            )
            session.add(run)
            session.flush()
            return run.id

    def run(
        self,
        run_id: UUID,
        *,
        adapter: CoverImageAdapter,
        storage: Storage,
        safety_gate: CoverSafetyGate,
    ) -> None:
        claim = secrets.token_hex(24)
        try:
            frozen = self._claim(run_id, claim)
        except Exception:
            self._record_preflight_failure(run_id)
            raise
        stored_keys: list[str] = []
        try:
            prepared, asset_images, input_manifest = self._prepare_assets(
                frozen,
                storage,
            )
            self._record_provider_disclosure(
                frozen,
                input_manifest=input_manifest,
            )
            plan = build_cover_plan(frozen.request)
            if plan.model_request is None:
                base = _template_base(frozen.request, asset_images)
                provider_request_id = None
            else:
                self._bind_prepared_images(adapter, prepared)
                try:
                    base = self._run_async(
                        adapter.generate_layer(plan.model_request)
                    )
                except ModelProviderError as error:
                    self._record_provider_failure(frozen, error)
                    raise
                metadata = getattr(adapter, "last_metadata", None)
                provider_request_id = getattr(
                    metadata,
                    "provider_request_id",
                    None,
                )
                self._record_provider_result(
                    frozen,
                    provider_request_id=provider_request_id,
                )
                provider_layer = self._png_bytes(base)
                provider_key = self._provider_staging_key(frozen)
                try:
                    storage.put_object(
                        provider_key,
                        provider_layer,
                        mime_type="image/png",
                    )
                except Exception as error:
                    self._record_object_failure(frozen, stored_keys)
                    raise RuntimeError("cover object write failed") from error
                stored_keys.append(provider_key)
                self._register_managed(
                    frozen,
                    object_key=provider_key,
                    business_referenced=False,
                )
            self._set_phase(
                frozen,
                CoverGenerationStatus.COMPOSITING,
                CoverAttemptStatus.COMPOSITING,
            )
            artifact = compose_cover(
                frozen.request,
                base=base,
                asset_images=asset_images,
            )
            self._set_phase(
                frozen,
                CoverGenerationStatus.RISK_SCANNING,
                CoverAttemptStatus.RISK_SCANNING,
            )
            safety = safety_gate.scan(
                png_bytes=artifact.png_bytes,
                workspace_id=frozen.workspace_id,
                platform=frozen.platform,
                content_id=frozen.content_id,
            )
            final_key = self._final_key(frozen)
            try:
                storage.put_object(
                    final_key,
                    artifact.png_bytes,
                    mime_type="image/png",
                )
            except Exception as error:
                self._record_object_failure(frozen, stored_keys)
                raise RuntimeError("cover object write failed") from error
            stored_keys.append(final_key)
            if self._publish_hook is not None:
                self._publish_hook()
            self._publish(
                frozen,
                artifact=artifact,
                safety=safety,
                provider_request_id=provider_request_id,
                final_key=final_key,
            )
        except ModelProviderError:
            raise
        except Exception:
            self._register_compensation(frozen, stored_keys)
            self._record_execution_failure(frozen)
            raise

    def cancel(self, run_id: UUID) -> UUID:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        with self._session_factory() as session, session.begin():
            run = self._owned_run(session, run_id)
            if run.status is not CoverGenerationStatus.SUCCEEDED:
                run.status = CoverGenerationStatus.CANCELLED
                run.error_code = None
                run.status_detail = "任务已取消。"
                run.completed_at = self._now()
                run.claim_token = None
                run.lease_expires_at = None
                attempt = self._latest_attempt(session, run.id)
                if attempt is not None and attempt.status is not CoverAttemptStatus.SUCCEEDED:
                    attempt.status = CoverAttemptStatus.CANCELLED
                    attempt.completed_at = self._now()
                    for managed in session.scalars(
                        select(ManagedObject).where(
                            ManagedObject.workspace_id == run.workspace_id,
                            ManagedObject.owner_type
                            == "cover_generation_attempt",
                            ManagedObject.owner_id == attempt.id,
                            ManagedObject.state
                            != ManagedObjectState.REFERENCED,
                        )
                    ):
                        managed.state = ManagedObjectState.SCHEDULED
                        managed.purge_at = self._now()
                        managed.claim_token = None
                        managed.lease_expires_at = None
            return run.id

    def retry(self, run_id: UUID, *, idempotency_key: str) -> UUID:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        if not idempotency_key.strip() or len(idempotency_key) > 200:
            raise ValueError("invalid cover retry idempotency key")
        with self._session_factory() as session, session.begin():
            run = self._owned_run(session, run_id)
            if idempotency_key in run.retry_idempotency_keys:
                return run.id
            if run.status not in {
                CoverGenerationStatus.FAILED,
                CoverGenerationStatus.CANCELLED,
                CoverGenerationStatus.PROVIDER_OUTCOME_UNKNOWN,
                CoverGenerationStatus.COMPENSATION_REQUIRED,
            }:
                raise ValueError("cover run is not manually retryable")
            run.retry_idempotency_keys = [
                *run.retry_idempotency_keys,
                idempotency_key,
            ]
            run.status = CoverGenerationStatus.QUEUED
            run.error_code = None
            run.status_detail = None
            run.completed_at = None
            run.claim_token = None
            run.lease_expires_at = None
            return run.id

    def _claim(self, run_id: UUID, claim_token: str) -> _FrozenCover:
        with self._session_factory() as session, session.begin():
            run = self._owned_run(session, run_id)
            if run.status is not CoverGenerationStatus.QUEUED:
                raise RuntimeError("cover generation is not queued")
            request = CoverRequest.model_validate(run.request_json)
            self._revalidate_binding(session, run)
            assets = self._frozen_assets(
                session,
                run=run,
                request=request,
            )
            previous = self._latest_attempt(session, run.id)
            run.status = CoverGenerationStatus.RUNNING
            run.claim_token = claim_token
            run.lease_expires_at = self._now() + timedelta(
                seconds=self._lease_seconds
            )
            run.attempt_count += 1
            requested_seed = request.image_parameters.get("seed")
            attempt = CoverArtifactAttempt(
                workspace_id=run.workspace_id,
                run_id=run.id,
                attempt_number=run.attempt_count,
                previous_attempt_id=previous.id if previous is not None else None,
                status=CoverAttemptStatus.RUNNING,
                provider=run.provider,
                model_id=run.model_id,
                region=run.region,
                model_config_id=run.model_config_id,
                configuration_version=run.configuration_version,
                contract_version=run.contract_version,
                cover_mode=run.cover_mode,
                request_fingerprint=run.request_fingerprint,
                prompt_hash=hashlib.sha256(request.prompt.encode()).hexdigest(),
                seed=requested_seed if isinstance(requested_seed, int) else None,
                requested_width=request.size.width,
                requested_height=request.size.height,
                provider_started_at=(
                    None
                    if request.mode is CoverMode.TEMPLATE
                    else self._now()
                ),
                billed_attempt_status=(
                    "not_billed"
                    if request.mode is CoverMode.TEMPLATE
                    else "prepared"
                ),
            )
            session.add(attempt)
            session.flush()
            return _FrozenCover(
                run_id=run.id,
                attempt_id=attempt.id,
                claim_token=claim_token,
                operation_version=run.operation_version,
                workspace_id=run.workspace_id,
                content_id=run.content_id,
                platform=run.platform,
                request=request,
                assets=assets,
                provider=run.provider,
                model_id=run.model_id,
                region=run.region,
                model_config_id=run.model_config_id,
                configuration_version=run.configuration_version,
                contract_version=run.contract_version,
                attempt_number=run.attempt_count,
            )

    def _prepare_assets(
        self,
        frozen: _FrozenCover,
        storage: Storage,
    ):
        from app.modules.models.adapters.qianwen_image import (
            QianwenPreparedImage,
            sanitize_reference_image,
        )

        prepared = []
        images: dict[UUID, Image.Image] = {}
        manifest: list[dict[str, object]] = []
        for item in frozen.assets:
            stored = storage.inspect_object(item.object_key)
            if (
                stored is None
                or stored.size != item.size
                or stored.mime_type != item.mime_type
            ):
                raise RuntimeError("reference asset changed or is unavailable")
            content = storage.get_object(item.object_key)
            if len(content) != item.size:
                raise RuntimeError("reference asset changed or is unavailable")
            cleaned = sanitize_reference_image(
                content,
                declared_mime_type=item.mime_type,
            )
            decoded = Image.open(BytesIO(cleaned.content))
            decoded.load()
            images[item.id] = decoded.convert("RGBA" if item.is_logo else "RGB")
            if item.provider_input and item.purpose is not None:
                prepared.append(
                    QianwenPreparedImage(
                        asset_id=item.id,
                        asset_version=1,
                        purpose=item.purpose,
                        content=cleaned.content,
                        mime_type=cleaned.mime_type,
                        width=cleaned.width,
                        height=cleaned.height,
                        sha256=cleaned.sha256,
                    )
                )
                manifest.append(
                    {
                        "asset_id": str(item.id),
                        "asset_version": item.version,
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "purpose": item.purpose.value,
                        "order": len(manifest) + 1,
                    }
                )
        self._revalidate_assets(frozen)
        return tuple(prepared), images, manifest

    def _record_provider_disclosure(
        self,
        frozen: _FrozenCover,
        *,
        input_manifest: list[dict[str, object]],
    ) -> None:
        with self._session_factory() as session, session.begin():
            run, attempt = self._current_claim(session, frozen)
            attempt.input_assets = input_manifest
            if frozen.request.mode is not CoverMode.TEMPLATE:
                run.status = CoverGenerationStatus.PROVIDER_CALLING
                attempt.status = CoverAttemptStatus.PROVIDER_CALLING
                attempt.billed_attempt_status = "provider_calling"

    def _record_provider_failure(
        self,
        frozen: _FrozenCover,
        error: "ModelProviderError",
    ) -> None:
        from app.modules.models.adapters.qianwen import ModelErrorCode

        with self._session_factory() as session, session.begin():
            try:
                run, attempt = self._current_claim(session, frozen)
            except RuntimeError:
                return
            unknown = (
                error.code is ModelErrorCode.PROVIDER_OUTCOME_UNKNOWN
            )
            run.status = (
                CoverGenerationStatus.PROVIDER_OUTCOME_UNKNOWN
                if unknown
                else CoverGenerationStatus.FAILED
            )
            attempt.status = (
                CoverAttemptStatus.PROVIDER_OUTCOME_UNKNOWN
                if unknown
                else CoverAttemptStatus.FAILED
            )
            run.error_code = error.code.value
            run.status_detail = safe_model_error_message(error.code)
            run.completed_at = self._now()
            run.claim_token = None
            run.lease_expires_at = None
            attempt.error_code = error.code.value
            attempt.billed_attempt_status = (
                "outcome_unknown" if unknown else "failed"
            )
            attempt.completed_at = self._now()

    def _record_provider_result(
        self,
        frozen: _FrozenCover,
        *,
        provider_request_id: str | None,
    ) -> None:
        with self._session_factory() as session, session.begin():
            run, attempt = self._current_claim(session, frozen)
            run.status = CoverGenerationStatus.VALIDATING
            attempt.status = CoverAttemptStatus.VALIDATING
            attempt.provider_request_id = provider_request_id
            attempt.provider_completed_at = self._now()
            attempt.billed_attempt_status = "completed"

    def _record_object_failure(
        self,
        frozen: _FrozenCover,
        stored_keys: list[str],
    ) -> None:
        self._register_compensation(frozen, stored_keys)
        with self._session_factory() as session, session.begin():
            run = self._owned_run(session, frozen.run_id)
            if run.status is CoverGenerationStatus.CANCELLED:
                return
            run.status = (
                CoverGenerationStatus.COMPENSATION_REQUIRED
                if stored_keys
                else CoverGenerationStatus.FAILED
            )
            run.error_code = "COVER_OBJECT_WRITE_FAILED"
            run.status_detail = "封面对象写入失败，需要受控清理。"
            run.completed_at = self._now()
            run.claim_token = None
            run.lease_expires_at = None
            attempt = session.get(CoverArtifactAttempt, frozen.attempt_id)
            if attempt is not None:
                attempt.status = (
                    CoverAttemptStatus.COMPENSATION_REQUIRED
                    if stored_keys
                    else CoverAttemptStatus.FAILED
                )
                attempt.error_code = "COVER_OBJECT_WRITE_FAILED"
                attempt.completed_at = self._now()

    def _record_execution_failure(self, frozen: _FrozenCover) -> None:
        with self._session_factory() as session, session.begin():
            run = session.get(CoverGenerationRun, frozen.run_id)
            attempt = session.get(CoverArtifactAttempt, frozen.attempt_id)
            if (
                run is None
                or run.status
                in {
                    CoverGenerationStatus.CANCELLED,
                    CoverGenerationStatus.SUCCEEDED,
                    CoverGenerationStatus.FAILED,
                    CoverGenerationStatus.PROVIDER_OUTCOME_UNKNOWN,
                    CoverGenerationStatus.COMPENSATION_REQUIRED,
                }
            ):
                return
            run.status = CoverGenerationStatus.FAILED
            run.error_code = "COVER_GENERATION_FAILED"
            run.status_detail = "封面生成未完成，请检查输入后重试。"
            run.completed_at = self._now()
            run.claim_token = None
            run.lease_expires_at = None
            if attempt is not None:
                attempt.status = CoverAttemptStatus.FAILED
                attempt.error_code = "COVER_GENERATION_FAILED"
                attempt.completed_at = self._now()

    def _record_preflight_failure(self, run_id: UUID) -> None:
        with self._session_factory() as session, session.begin():
            run = session.scalar(
                select(CoverGenerationRun).where(
                    CoverGenerationRun.id == run_id,
                    CoverGenerationRun.workspace_id
                    == self._context.workspace_id,
                )
            )
            if run is None or run.status is not CoverGenerationStatus.QUEUED:
                return
            run.status = CoverGenerationStatus.FAILED
            run.error_code = "COVER_GENERATION_FAILED"
            run.status_detail = "封面任务输入或配置已变化，请重新创建任务。"
            run.completed_at = self._now()

    def _publish(
        self,
        frozen: _FrozenCover,
        *,
        artifact: CoverArtifact,
        safety: CoverSafetyResult,
        provider_request_id: str | None,
        final_key: str,
    ) -> None:
        output_sha = hashlib.sha256(artifact.png_bytes).hexdigest()
        with self._session_factory() as session, session.begin():
            run, attempt = self._current_claim(session, frozen)
            self._register_managed_in_session(
                session,
                frozen,
                object_key=final_key,
                business_referenced=True,
            )
            attempt.status = CoverAttemptStatus.SUCCEEDED
            attempt.provider_request_id = provider_request_id
            attempt.billed_attempt_status = (
                attempt.billed_attempt_status
                if frozen.request.mode is not CoverMode.TEMPLATE
                else "not_billed"
            )
            attempt.output_object_key = final_key
            attempt.output_object_version = f"sha256:{output_sha[:16]}"
            attempt.output_sha256 = output_sha
            attempt.output_mime_type = "image/png"
            attempt.output_width = frozen.request.size.width
            attempt.output_height = frozen.request.size.height
            attempt.layout_version = "cover-layout-v1"
            attempt.ocr_model_version = safety.ocr_model_version
            attempt.ocr_confidence = safety.ocr_confidence
            attempt.risk_scan_id = safety.risk_scan_id
            attempt.risk_rule_version = safety.risk_rule_version
            attempt.requires_human_review = safety.requires_human_review
            attempt.publish_eligible = (
                not safety.high_risk
                and not safety.requires_human_review
            )
            attempt.disclaimer = safety.disclaimer
            attempt.error_code = None
            attempt.completed_at = self._now()
            run.status = CoverGenerationStatus.SUCCEEDED
            run.error_code = None
            run.status_detail = (
                "封面已生成，仍需在 Web 中人工确认。"
            )
            run.completed_at = self._now()
            run.claim_token = None
            run.lease_expires_at = None

    def _register_compensation(
        self,
        frozen: _FrozenCover,
        object_keys: list[str],
    ) -> None:
        for key in object_keys:
            try:
                self._register_managed(
                    frozen,
                    object_key=key,
                    business_referenced=False,
                )
            except Exception:
                continue
        with self._session_factory() as session, session.begin():
            run = session.get(CoverGenerationRun, frozen.run_id)
            if run is None:
                return
            if run.status is CoverGenerationStatus.CANCELLED:
                for managed in session.scalars(
                    select(ManagedObject).where(
                        ManagedObject.workspace_id == frozen.workspace_id,
                        ManagedObject.owner_type
                        == "cover_generation_attempt",
                        ManagedObject.owner_id == frozen.attempt_id,
                        ManagedObject.state
                        != ManagedObjectState.REFERENCED,
                    )
                ):
                    managed.state = ManagedObjectState.SCHEDULED
                    managed.purge_at = self._now()
                    managed.claim_token = None
                    managed.lease_expires_at = None
                return
            if object_keys and run.status is not CoverGenerationStatus.SUCCEEDED:
                run.status = CoverGenerationStatus.COMPENSATION_REQUIRED
                run.error_code = run.error_code or "COVER_COMPENSATION_REQUIRED"
                run.status_detail = "封面暂存对象需要受控清理。"
                run.claim_token = None
                run.lease_expires_at = None
            attempt = session.get(CoverArtifactAttempt, frozen.attempt_id)
            if (
                attempt is not None
                and attempt.status
                not in {
                    CoverAttemptStatus.SUCCEEDED,
                    CoverAttemptStatus.CANCELLED,
                }
                and object_keys
            ):
                attempt.status = CoverAttemptStatus.COMPENSATION_REQUIRED
                attempt.error_code = (
                    attempt.error_code or "COVER_COMPENSATION_REQUIRED"
                )

    def _register_managed(
        self,
        frozen: _FrozenCover,
        *,
        object_key: str,
        business_referenced: bool,
    ) -> ManagedObject:
        with self._session_factory() as session, session.begin():
            return self._register_managed_in_session(
                session,
                frozen,
                object_key=object_key,
                business_referenced=business_referenced,
            )

    def _register_managed_in_session(
        self,
        session: Session,
        frozen: _FrozenCover,
        *,
        object_key: str,
        business_referenced: bool,
    ) -> ManagedObject:
        prefix = (
            f"workspaces/{frozen.workspace_id}/generated-covers/"
            f"{frozen.run_id}/{frozen.attempt_id}/"
        )
        return RetentionService(
            session,
            self._context,
            now=self._now,
        ).register_managed_object(
            owner_type="cover_generation_attempt",
            owner_id=frozen.attempt_id,
            object_key=object_key,
            managed_prefix=prefix,
            purge_at=self._now() + timedelta(days=1),
            claim_token=frozen.claim_token,
            lease_expires_at=self._now()
            + timedelta(seconds=self._lease_seconds),
            business_referenced=business_referenced,
        )

    def _set_phase(
        self,
        frozen: _FrozenCover,
        run_status: CoverGenerationStatus,
        attempt_status: CoverAttemptStatus,
    ) -> None:
        with self._session_factory() as session, session.begin():
            run, attempt = self._current_claim(session, frozen)
            run.status = run_status
            attempt.status = attempt_status

    def _revalidate_assets(self, frozen: _FrozenCover) -> None:
        with self._session_factory() as session, session.begin():
            run, _ = self._current_claim(session, frozen)
            self._revalidate_binding(session, run)
            current = self._frozen_assets(
                session,
                run=run,
                request=frozen.request,
            )
            if current != frozen.assets:
                raise RuntimeError("reference asset changed or is unavailable")

    def _frozen_assets(
        self,
        session: Session,
        *,
        run: CoverGenerationRun,
        request: CoverRequest,
    ) -> tuple[_FrozenAsset, ...]:
        by_reference = {
            reference.asset_id: reference
            for reference in request.references
        }
        asset_ids = list(by_reference)
        if request.logo_asset_id is not None:
            asset_ids.append(request.logo_asset_id)
        if not asset_ids:
            return ()
        rows = list(
            session.scalars(
                select(ContentAsset)
                .where(
                    ContentAsset.id.in_(asset_ids),
                    ContentAsset.workspace_id == run.workspace_id,
                    ContentAsset.content_id == run.content_id,
                )
            )
        )
        by_id = {row.id: row for row in rows}
        if set(by_id) != set(asset_ids):
            raise LookupError("reference asset not found")
        result: list[_FrozenAsset] = []
        for asset_id in asset_ids:
            asset = by_id[asset_id]
            blocked = session.scalar(
                select(ManagedObject).where(
                    ManagedObject.workspace_id == run.workspace_id,
                    ManagedObject.object_key == asset.object_key,
                    ManagedObject.state.in_(
                        (
                            ManagedObjectState.SCHEDULED,
                            ManagedObjectState.RETRYING,
                            ManagedObjectState.DELETED,
                        )
                    ),
                )
            )
            if blocked is not None:
                raise RuntimeError(
                    "reference asset is scheduled for cleanup or unavailable"
                )
            reference = by_reference.get(asset.id)
            result.append(
                _FrozenAsset(
                    id=asset.id,
                    version=asset.updated_at.isoformat(),
                    object_key=asset.object_key,
                    mime_type=asset.mime_type,
                    size=asset.size,
                    purpose=reference.purpose if reference else None,
                    provider_input=(
                        reference.provider_input if reference else False
                    ),
                    is_logo=asset.id == request.logo_asset_id,
                )
            )
        return tuple(result)

    def _validate_assets(
        self,
        session: Session,
        *,
        content: Content,
        request: CoverRequest,
    ) -> None:
        synthetic = CoverGenerationRun(
            workspace_id=content.workspace_id,
            requested_by=self._context.member_id or UUID(int=0),
            account_id=content.account_id,
            content_id=content.id,
            platform=content.platform.value,
            provider="validation",
            model_id="validation",
            contract_version="validation",
            configuration_version="validation",
            cover_mode=request.mode.value,
            request_json={},
            request_fingerprint="0" * 64,
            idempotency_key="validation",
            status=CoverGenerationStatus.QUEUED,
        )
        self._frozen_assets(session, run=synthetic, request=request)

    def _binding(
        self,
        session: Session,
        request: CoverRequest,
    ) -> tuple[str, str, str | None, UUID | None, str, str]:
        if request.mode is CoverMode.TEMPLATE:
            return (
                "template",
                "programmatic-cover-v1",
                None,
                None,
                "programmatic-v1",
                "programmatic-cover-layer-v1",
            )
        if request.model_config_id is None:
            raise ValueError("image model config is required")
        config = session.scalar(
            select(ModelConfig).where(
                ModelConfig.id == request.model_config_id,
                ModelConfig.workspace_id == self._context.workspace_id,
                ModelConfig.status != ModelConfigStatus.INCOMPATIBLE,
            )
        )
        if config is None:
            raise LookupError("model config not found")
        catalog = get_catalog_entry(config.provider, config.model_id)
        if (
            "image" not in config.capabilities
            or Capability.IMAGE not in catalog.capabilities
            or config.status.value != catalog.adapter_status.value
            or config.region is None
        ):
            raise ValueError("model config does not provide image capability")
        return (
            config.provider,
            config.model_id,
            config.region,
            config.id,
            model_configuration_version(config),
            catalog.contract_version,
        )

    def _revalidate_binding(
        self,
        session: Session,
        run: CoverGenerationRun,
    ) -> None:
        if run.model_config_id is None:
            if run.provider != "template":
                raise RuntimeError("cover model binding changed")
            return
        config = session.scalar(
            select(ModelConfig).where(
                ModelConfig.id == run.model_config_id,
                ModelConfig.workspace_id == run.workspace_id,
                ModelConfig.status != ModelConfigStatus.INCOMPATIBLE,
            )
        )
        if config is None:
            raise RuntimeError("cover model binding changed")
        catalog = get_catalog_entry(config.provider, config.model_id)
        if (
            config.provider != run.provider
            or config.model_id != run.model_id
            or config.region != run.region
            or catalog.contract_version != run.contract_version
            or model_configuration_version(config)
            != run.configuration_version
        ):
            raise RuntimeError("cover model binding changed")

    def _current_claim(
        self,
        session: Session,
        frozen: _FrozenCover,
    ) -> tuple[CoverGenerationRun, CoverArtifactAttempt]:
        run = self._owned_run(session, frozen.run_id)
        attempt = session.get(CoverArtifactAttempt, frozen.attempt_id)
        if (
            attempt is None
            or attempt.workspace_id != frozen.workspace_id
            or run.claim_token != frozen.claim_token
            or run.lease_expires_at is None
            or run.lease_expires_at < self._now()
            or run.operation_version < frozen.operation_version
            or run.status
            in {
                CoverGenerationStatus.CANCELLED,
                CoverGenerationStatus.SUCCEEDED,
                CoverGenerationStatus.FAILED,
                CoverGenerationStatus.PROVIDER_OUTCOME_UNKNOWN,
            }
        ):
            raise RuntimeError(
                "cover generation claim is no longer current"
            )
        return run, attempt

    def _owned_run(
        self,
        session: Session,
        run_id: UUID,
    ) -> CoverGenerationRun:
        run = session.scalar(
            select(CoverGenerationRun).where(
                CoverGenerationRun.id == run_id,
                CoverGenerationRun.workspace_id
                == self._context.workspace_id,
            )
        )
        if run is None:
            raise LookupError("cover generation run not found")
        return run

    @staticmethod
    def _latest_attempt(
        session: Session,
        run_id: UUID,
    ) -> CoverArtifactAttempt | None:
        return session.scalar(
            select(CoverArtifactAttempt)
            .where(CoverArtifactAttempt.run_id == run_id)
            .order_by(CoverArtifactAttempt.attempt_number.desc())
        )

    @staticmethod
    def _fingerprint(
        content_id: UUID,
        request: CoverRequest,
    ) -> str:
        payload = {
            "content_id": str(content_id),
            "request": request.model_dump(mode="json"),
        }
        return hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

    @staticmethod
    def _bind_prepared_images(
        adapter: CoverImageAdapter,
        images: tuple[object, ...],
    ) -> None:
        binder = getattr(adapter, "bind_prepared_images", None)
        if callable(binder):
            binder(images)
        else:
            setattr(adapter, "prepared_images", images)

    @staticmethod
    def _run_async(awaitable):
        import asyncio

        return asyncio.run(awaitable)

    @staticmethod
    def _png_bytes(image: Image.Image) -> bytes:
        output = BytesIO()
        image.convert("RGB").save(
            output,
            format="PNG",
            optimize=False,
            compress_level=9,
        )
        return output.getvalue()

    @staticmethod
    def _provider_staging_key(frozen: _FrozenCover) -> str:
        return (
            f"workspaces/{frozen.workspace_id}/generated-covers/"
            f"{frozen.run_id}/{frozen.attempt_id}/provider-layer.png"
        )

    @staticmethod
    def _final_key(frozen: _FrozenCover) -> str:
        return (
            f"workspaces/{frozen.workspace_id}/generated-covers/"
            f"{frozen.run_id}/{frozen.attempt_id}/final.png"
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("cover generation clock must be timezone-aware")
        return value
