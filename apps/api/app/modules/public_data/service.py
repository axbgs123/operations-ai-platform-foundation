from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import json
import secrets
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionFactory, utc_now, uuid7
from app.core.security import WorkspaceContext
from app.modules.analysis.service import AnalysisService, account_auto_analysis_enabled
from app.modules.analysis.tasks import enqueue_analysis
from app.modules.content.account_models import Platform
from app.modules.content.models import Content, ContentStatus
from app.modules.metrics.models import SnapshotSource
from app.modules.metrics.schemas import SnapshotMetricInput
from app.modules.metrics.snapshot_service import SnapshotService
from app.modules.models.config_service import SecretCipher
from app.modules.public_data.contracts import PublicDataProvider, PublicProviderError
from app.modules.public_data.models import (
    BindingStatus,
    CollectionJobStatus,
    ProviderConfigStatus,
    PublicCollectionAttempt,
    PublicCollectionJob,
    PublicDataProviderConfig,
    PublicObservation,
    PublishedContentBinding,
)
from app.modules.public_data.providers import MockPublicDataProvider, TikHubProvider
from app.modules.workspace.permissions import Permission, require_permission


SCHEDULE_WINDOWS = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "72h": timedelta(hours=72),
    "7d": timedelta(days=7),
}
ALLOWED_HOSTS = {
    Platform.DOUYIN: ("douyin.com",),
    Platform.XIAOHONGSHU: ("xiaohongshu.com", "xhslink.com"),
}
RETRY_DELAYS = (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=20))


def _reserve_provider_call(config: PublicDataProviderConfig) -> None:
    today = utc_now().date()
    if config.daily_usage_date != today:
        config.daily_usage_date = today
        config.daily_requests_used = 0
    if config.daily_requests_used >= config.daily_request_limit:
        raise PublicProviderError("PUBLIC_PROVIDER_DAILY_LIMIT_REACHED", retryable=True)
    config.daily_requests_used += 1


def _provider_from_config(config: PublicDataProviderConfig) -> PublicDataProvider:
    settings = get_settings()
    if settings.app_mock_mode:
        return MockPublicDataProvider()
    key = SecretCipher(settings.model_secret_encryption_key.get_secret_value()).decrypt(
        config.encrypted_api_key
    )
    return TikHubProvider(
        api_key=key,
        endpoint_region=config.endpoint_region,
    )


def _valid_public_url(platform: Platform, value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("作品链接必须是 HTTPS 公开链接")
    host = parsed.hostname.lower().rstrip(".")
    if not any(
        host == allowed or host.endswith(f".{allowed}")
        for allowed in ALLOWED_HOSTS[platform]
    ):
        raise ValueError("作品链接与内容平台不匹配")
    return value


def _job_payload(job: PublicCollectionJob) -> dict[str, object]:
    return {
        "id": job.id,
        "target_window": job.target_window,
        "due_at": job.due_at,
        "next_attempt_at": job.next_attempt_at,
        "status": job.status.value,
        "attempt_count": job.attempt_count,
        "snapshot_id": job.snapshot_id,
        "safe_error_code": job.safe_error_code,
    }


class PublicDataService:
    def __init__(self, session: Session, context: WorkspaceContext) -> None:
        self._session = session
        self._context = context

    def _config(self) -> PublicDataProviderConfig | None:
        return self._session.scalar(
            select(PublicDataProviderConfig).where(
                PublicDataProviderConfig.workspace_id == self._context.workspace_id,
                PublicDataProviderConfig.provider == "tikhub",
            )
        )

    def save_config(
        self,
        *,
        api_key: str,
        endpoint_region: str,
        daily_request_limit: int,
    ) -> PublicDataProviderConfig:
        require_permission(self._context.role, Permission.MANAGE_DATA_PROVIDERS)
        encrypted = SecretCipher(
            get_settings().model_secret_encryption_key.get_secret_value()
        ).encrypt(api_key)
        config = self._config()
        if config is None:
            config = PublicDataProviderConfig(
                workspace_id=self._context.workspace_id,
                encrypted_api_key=encrypted,
                endpoint_region=endpoint_region,
                daily_request_limit=daily_request_limit,
            )
            self._session.add(config)
        else:
            config.encrypted_api_key = encrypted
            config.endpoint_region = endpoint_region
            config.daily_request_limit = daily_request_limit
            config.configuration_revision += 1
            config.status = ProviderConfigStatus.UNVERIFIED
            config.safe_error_code = None
        self._session.flush()
        return config

    def read_config(self) -> PublicDataProviderConfig | None:
        require_permission(self._context.role, Permission.READ_CONTENT)
        return self._config()

    def test_config(self) -> tuple[PublicDataProviderConfig, bool]:
        require_permission(self._context.role, Permission.MANAGE_DATA_PROVIDERS)
        config = self._config()
        if config is None:
            raise LookupError("public data provider is not configured")
        checked_at = utc_now()
        _reserve_provider_call(config)
        try:
            if get_settings().app_mock_mode:
                provider: PublicDataProvider = MockPublicDataProvider()
            else:
                key = SecretCipher(
                    get_settings().model_secret_encryption_key.get_secret_value()
                ).decrypt(config.encrypted_api_key)
                provider = TikHubProvider(
                    api_key=key,
                    endpoint_region=config.endpoint_region,
                )
            provider.test_connection()
        except PublicProviderError as error:
            config.status = ProviderConfigStatus.UNVERIFIED
            config.safe_error_code = error.code
            success = False
        else:
            config.status = ProviderConfigStatus.VERIFIED
            config.safe_error_code = None
            success = True
        config.last_tested_at = checked_at
        self._session.flush()
        return config, success

    def bind_content(
        self,
        content_id: UUID,
        *,
        public_url: str,
        published_at: datetime,
        platform_content_id: str | None,
    ) -> PublishedContentBinding:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        content = self._session.scalar(
            select(Content).where(
                Content.id == content_id,
                Content.workspace_id == self._context.workspace_id,
                Content.deleted_at.is_(None),
            )
        )
        if content is None:
            raise LookupError("content not found")
        if published_at.tzinfo is None:
            raise ValueError("发布时间必须包含时区")
        if published_at.astimezone(UTC) > utc_now() + timedelta(minutes=5):
            raise ValueError("发布时间不能晚于当前时间")
        public_url = _valid_public_url(content.platform, public_url)
        config = self._config()
        if config is None and not get_settings().app_mock_mode:
            raise LookupError("public data provider is not configured")
        if (
            config is not None
            and config.status is not ProviderConfigStatus.VERIFIED
            and not get_settings().app_mock_mode
        ):
            raise ValueError("请先完成 TikHub 连接测试")
        provider = (
            MockPublicDataProvider()
            if config is None
            else _provider_from_config(config)
        )
        if config is not None:
            _reserve_provider_call(config)
            self._session.commit()
        resolved = provider.resolve_content(
            platform=content.platform,
            public_url=public_url,
            platform_content_id=platform_content_id,
        )
        binding = self._session.scalar(
            select(PublishedContentBinding).where(
                PublishedContentBinding.content_id == content.id,
                PublishedContentBinding.workspace_id == self._context.workspace_id,
            )
        )
        if binding is None:
            binding = PublishedContentBinding(
                workspace_id=self._context.workspace_id,
                content_id=content.id,
                account_id=content.account_id,
                platform=content.platform,
                public_url=resolved.public_url,
                platform_content_id=resolved.platform_content_id,
                locator=resolved.locator,
                published_at=published_at.astimezone(UTC),
                last_verified_at=utc_now(),
            )
            self._session.add(binding)
            self._session.flush()
        else:
            binding.public_url = resolved.public_url
            binding.platform_content_id = resolved.platform_content_id
            binding.locator = resolved.locator
            binding.published_at = published_at.astimezone(UTC)
            binding.status = BindingStatus.ACTIVE
            binding.last_verified_at = utc_now()
            binding.safe_error_code = None
        content.work_url = resolved.public_url
        content.platform_content_id = resolved.platform_content_id
        content.published_at = published_at.astimezone(UTC)
        content.status = ContentStatus.PUBLISHED
        content.published_title = content.published_title or content.title
        content.published_body = content.published_body or content.body
        self._replace_schedule(binding)
        self._session.flush()
        return binding

    def _replace_schedule(self, binding: PublishedContentBinding) -> None:
        now = utc_now()
        existing = {
            job.target_window: job
            for job in self._session.scalars(
                select(PublicCollectionJob).where(
                    PublicCollectionJob.binding_id == binding.id
                )
            )
        }
        for label, delay in SCHEDULE_WINDOWS.items():
            due_at = binding.published_at + delay
            job = existing.get(label)
            if due_at < now:
                if job is not None and job.status in {
                    CollectionJobStatus.SCHEDULED,
                    CollectionJobStatus.RETRYING,
                }:
                    job.status = CollectionJobStatus.CANCELLED
                continue
            if job is None:
                self._session.add(
                    PublicCollectionJob(
                        workspace_id=binding.workspace_id,
                        binding_id=binding.id,
                        target_window=label,
                        due_at=due_at,
                        next_attempt_at=due_at,
                    )
                )
                continue
            if job.status is not CollectionJobStatus.SUCCEEDED:
                job.due_at = due_at
                job.next_attempt_at = due_at
                job.status = CollectionJobStatus.SCHEDULED
                job.attempt_count = 0
                job.completed_at = None
                job.safe_error_code = None
                job.claim_token = None
                job.lease_expires_at = None

        missed = any(
            binding.published_at + delay < now for delay in SCHEDULE_WINDOWS.values()
        )
        if missed and not any(
            job.target_window.startswith("late-")
            and job.status
            in {
                CollectionJobStatus.SCHEDULED,
                CollectionJobStatus.RUNNING,
                CollectionJobStatus.RETRYING,
                CollectionJobStatus.SUCCEEDED,
            }
            for job in existing.values()
        ):
            self._session.add(
                PublicCollectionJob(
                    workspace_id=binding.workspace_id,
                    binding_id=binding.id,
                    target_window=f"late-{uuid7()}",
                    due_at=now,
                    next_attempt_at=now,
                )
            )

    def read_binding(self, content_id: UUID) -> PublishedContentBinding:
        require_permission(self._context.role, Permission.READ_CONTENT)
        binding = self._session.scalar(
            select(PublishedContentBinding).where(
                PublishedContentBinding.content_id == content_id,
                PublishedContentBinding.workspace_id == self._context.workspace_id,
            )
        )
        if binding is None:
            raise LookupError("public content binding not found")
        return binding

    def binding_payload(self, binding: PublishedContentBinding) -> dict[str, object]:
        jobs = list(
            self._session.scalars(
                select(PublicCollectionJob)
                .where(PublicCollectionJob.binding_id == binding.id)
                .order_by(PublicCollectionJob.due_at, PublicCollectionJob.id)
            )
        )
        return {
            "id": binding.id,
            "content_id": binding.content_id,
            "account_id": binding.account_id,
            "platform": binding.platform.value,
            "public_url": binding.public_url,
            "platform_content_id": binding.platform_content_id,
            "published_at": binding.published_at,
            "status": binding.status.value,
            "last_verified_at": binding.last_verified_at,
            "safe_error_code": binding.safe_error_code,
            "jobs": [_job_payload(job) for job in jobs],
        }

    def collect_now(self, content_id: UUID) -> PublicCollectionJob:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        binding = self.read_binding(content_id)
        now = utc_now()
        job = PublicCollectionJob(
            workspace_id=self._context.workspace_id,
            binding_id=binding.id,
            target_window=f"manual-{uuid7()}",
            due_at=now,
            next_attempt_at=now,
        )
        self._session.add(job)
        self._session.flush()
        return job


def run_collection_job(job_id: UUID) -> None:
    with SessionFactory() as session:
        job = session.scalar(
            select(PublicCollectionJob)
            .where(PublicCollectionJob.id == job_id)
            .with_for_update()
        )
        if job is None or job.status not in {
            CollectionJobStatus.SCHEDULED,
            CollectionJobStatus.RETRYING,
        }:
            return
        binding = session.get(PublishedContentBinding, job.binding_id)
        if binding is None or binding.status is not BindingStatus.ACTIVE:
            job.status = CollectionJobStatus.FAILED
            job.safe_error_code = "PUBLIC_BINDING_UNAVAILABLE"
            session.commit()
            return
        config = session.scalar(
            select(PublicDataProviderConfig).where(
                PublicDataProviderConfig.workspace_id == job.workspace_id,
                PublicDataProviderConfig.provider == "tikhub",
            )
        )
        if config is None and not get_settings().app_mock_mode:
            job.status = CollectionJobStatus.FAILED
            job.safe_error_code = "PUBLIC_PROVIDER_CONFIGURATION_REQUIRED"
            session.commit()
            return
        if config is not None:
            try:
                _reserve_provider_call(config)
            except PublicProviderError as error:
                job.status = CollectionJobStatus.RETRYING
                tomorrow = utc_now() + timedelta(days=1)
                job.next_attempt_at = datetime(
                    tomorrow.year,
                    tomorrow.month,
                    tomorrow.day,
                    tzinfo=UTC,
                )
                job.safe_error_code = error.code
                session.commit()
                return
        job.status = CollectionJobStatus.RUNNING
        job.attempt_count += 1
        job.claim_token = secrets.token_hex(16)
        job.lease_expires_at = utc_now() + timedelta(minutes=5)
        attempt = PublicCollectionAttempt(
            workspace_id=job.workspace_id,
            job_id=job.id,
            attempt_number=job.attempt_count,
            provider=(
                "mock" if config is None or get_settings().app_mock_mode else "tikhub"
            ),
            endpoint_contract="pending",
            started_at=utc_now(),
        )
        session.add(attempt)
        session.commit()
        locator = dict(binding.locator)
        platform = binding.platform

    try:
        provider = (
            MockPublicDataProvider()
            if config is None
            else _provider_from_config(config)
        )
        result = provider.fetch_content_metrics(platform=platform, locator=locator)
        if not any(value is not None for value in result.metrics.values()):
            raise PublicProviderError("PUBLIC_METRICS_EMPTY", retryable=False)
    except PublicProviderError as error:
        with SessionFactory() as session:
            job = session.get(PublicCollectionJob, job_id)
            attempt = session.scalar(
                select(PublicCollectionAttempt).where(
                    PublicCollectionAttempt.job_id == job_id,
                    PublicCollectionAttempt.attempt_number
                    == (job.attempt_count if job else 0),
                )
            )
            if job is None:
                return
            job.claim_token = None
            job.lease_expires_at = None
            job.safe_error_code = error.code
            if error.retryable and job.attempt_count < len(RETRY_DELAYS):
                job.status = CollectionJobStatus.RETRYING
                job.next_attempt_at = utc_now() + RETRY_DELAYS[job.attempt_count - 1]
            else:
                job.status = CollectionJobStatus.FAILED
            if attempt is not None:
                attempt.completed_at = utc_now()
                attempt.safe_error_code = error.code
            session.commit()
        return

    with SessionFactory() as session:
        job = session.get(PublicCollectionJob, job_id)
        if job is None or job.status is not CollectionJobStatus.RUNNING:
            return
        binding = session.get(PublishedContentBinding, job.binding_id)
        if binding is None:
            return
        raw_sha = sha256(
            json.dumps(
                result.raw_response,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        observation = PublicObservation(
            workspace_id=job.workspace_id,
            binding_id=binding.id,
            provider=provider.name,
            platform=binding.platform,
            platform_content_id=binding.platform_content_id,
            endpoint_contract=result.endpoint_contract,
            parser_version="public-metrics-v1",
            provider_fetched_at=result.fetched_at,
            received_at=utc_now(),
            raw_response=result.raw_response,
            raw_sha256=raw_sha,
            normalized_metrics=result.metrics,
        )
        session.add(observation)
        session.flush()
        context = WorkspaceContext(
            workspace_id=job.workspace_id, member_id=None, role="admin"
        )
        metric_inputs = [
            SnapshotMetricInput(
                key=key,
                raw_value=None if value is None else Decimal(str(value)),
            )
            for key, value in result.metrics.items()
        ]
        snapshot_service = SnapshotService(session, context)
        snapshot = snapshot_service.create(
            binding.content_id,
            collected_at=result.fetched_at,
            source=SnapshotSource.PUBLIC_API,
            metrics=metric_inputs,
            original_screenshot_asset_id=None,
        )
        snapshot_service.confirm(binding.content_id, snapshot.id)
        attempt = session.scalar(
            select(PublicCollectionAttempt).where(
                PublicCollectionAttempt.job_id == job.id,
                PublicCollectionAttempt.attempt_number == job.attempt_count,
            )
        )
        if attempt is not None:
            attempt.endpoint_contract = result.endpoint_contract
            attempt.provider_request_id = result.provider_request_id
            attempt.completed_at = utc_now()
            attempt.succeeded = True
        job.observation_id = observation.id
        job.snapshot_id = snapshot.id
        job.status = CollectionJobStatus.SUCCEEDED
        job.completed_at = utc_now()
        job.safe_error_code = None
        job.claim_token = None
        job.lease_expires_at = None
        auto_analyze = account_auto_analysis_enabled(
            session, job.workspace_id, binding.account_id
        )
        analysis_run_id: UUID | None = None
        if auto_analyze:
            run, should_enqueue, _ = AnalysisService(session, context).request(
                binding.content_id,
                trigger_kind="auto",
            )
            if should_enqueue:
                analysis_run_id = run.id
        session.commit()
    if analysis_run_id is not None:
        enqueue_analysis(analysis_run_id)


def run_due_collection_jobs(*, limit: int = 20) -> int:
    now = utc_now()
    with SessionFactory() as session:
        job_ids = list(
            session.scalars(
                select(PublicCollectionJob.id)
                .where(
                    PublicCollectionJob.status.in_(
                        [CollectionJobStatus.SCHEDULED, CollectionJobStatus.RETRYING]
                    ),
                    PublicCollectionJob.next_attempt_at <= now,
                )
                .order_by(PublicCollectionJob.next_attempt_at, PublicCollectionJob.id)
                .limit(limit)
            )
        )
    for job_id in job_ids:
        run_collection_job(job_id)
    return len(job_ids)
