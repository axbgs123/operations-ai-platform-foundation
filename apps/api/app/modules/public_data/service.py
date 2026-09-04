from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from collections.abc import Mapping
from hashlib import sha256
import json
import re
import secrets
from statistics import median
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
    CommentDemandAnalysis,
    CollectionJobStatus,
    CompetitorAccount,
    CompetitorObservation,
    ProviderConfigStatus,
    PublicCollectionAttempt,
    PublicCollectionJob,
    PublicDataProviderConfig,
    PublicObservation,
    PublicTrendSearch,
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

COMMENT_THEMES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("价格与购买", ("多少钱", "价格", "哪里买", "怎么买", "购买", "链接")),
    ("教程与使用", ("怎么", "如何", "教程", "安装", "使用", "操作")),
    ("功能建议", ("希望", "建议", "增加", "支持", "能不能", "可以不")),
    ("对比与选择", ("区别", "相比", "对比", "哪个好", "选择")),
    ("效果与反馈", ("效果", "实际", "好用", "复杂", "节省", "体验")),
)


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


def _raw_sha(payload: dict[str, object]) -> str:
    return sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _account_id_from_url(platform: Platform, value: str) -> str | None:
    path = urlsplit(value).path
    pattern = (
        r"/user/([^/?]+)" if platform is Platform.DOUYIN else r"/user/profile/([^/?]+)"
    )
    match = re.search(pattern, path)
    return match.group(1) if match else None


def _analyze_comment_texts(
    comments: list[str],
) -> tuple[list[dict[str, object]], list[str]]:
    grouped: dict[str, list[str]] = {name: [] for name, _ in COMMENT_THEMES}
    questions: list[str] = []
    for comment in comments:
        if any(
            marker in comment
            for marker in ("?", "？", "怎么", "如何", "能不能", "可以吗")
        ):
            questions.append(comment)
        for name, keywords in COMMENT_THEMES:
            if any(keyword in comment for keyword in keywords):
                grouped[name].append(comment)
                break
    themes = [
        {"theme": name, "count": len(items), "examples": items[:3]}
        for name, items in grouped.items()
        if items
    ]
    themes.sort(
        key=lambda item: (
            -(item["count"] if isinstance(item["count"], int) else 0),
            str(item["theme"]),
        )
    )
    return themes, questions[:10]


def _engagement(post: Mapping[str, object]) -> float:
    total = 0.0
    for key in ("likes", "comments", "favorites", "shares"):
        value = post.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            total += float(value)
    return total


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
                    # Keep the generated label inside the database's VARCHAR(40).
                    # UUID.hex is still unique for this per-binding recovery job.
                    target_window=f"late-{uuid7().hex}",
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
            target_window=f"manual-{uuid7().hex}",
            due_at=now,
            next_attempt_at=now,
        )
        self._session.add(job)
        self._session.flush()
        return job

    def create_competitor(
        self,
        *,
        platform: Platform,
        name: str,
        public_url: str,
        platform_account_id: str | None,
        collection_interval_hours: int,
    ) -> CompetitorAccount:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        public_url = _valid_public_url(platform, public_url)
        resolved_id = (
            platform_account_id or _account_id_from_url(platform, public_url) or ""
        ).strip()
        if not resolved_id:
            raise ValueError("无法从主页链接识别账号，请补充主页 ID")
        existing = self._session.scalar(
            select(CompetitorAccount).where(
                CompetitorAccount.workspace_id == self._context.workspace_id,
                CompetitorAccount.platform == platform,
                CompetitorAccount.platform_account_id == resolved_id,
            )
        )
        if existing is not None:
            existing.name = name.strip()
            existing.public_url = public_url
            existing.collection_interval_hours = collection_interval_hours
            existing.status = BindingStatus.ACTIVE
            existing.safe_error_code = None
            self._session.flush()
            return existing
        account = CompetitorAccount(
            workspace_id=self._context.workspace_id,
            platform=platform,
            name=name.strip(),
            public_url=public_url,
            platform_account_id=resolved_id,
            next_collection_at=utc_now(),
            collection_interval_hours=collection_interval_hours,
        )
        self._session.add(account)
        self._session.flush()
        return account

    def _latest_competitor_observation(
        self, account_id: UUID
    ) -> CompetitorObservation | None:
        return self._session.scalar(
            select(CompetitorObservation)
            .where(
                CompetitorObservation.workspace_id == self._context.workspace_id,
                CompetitorObservation.competitor_account_id == account_id,
            )
            .order_by(
                CompetitorObservation.provider_fetched_at.desc(),
                CompetitorObservation.id.desc(),
            )
            .limit(1)
        )

    def competitor_payload(self, account: CompetitorAccount) -> dict[str, object]:
        latest = self._latest_competitor_observation(account.id)
        return {
            "id": account.id,
            "platform": account.platform.value,
            "name": account.name,
            "public_url": account.public_url,
            "platform_account_id": account.platform_account_id,
            "status": account.status.value,
            "collection_interval_hours": account.collection_interval_hours,
            "next_collection_at": account.next_collection_at,
            "last_collected_at": account.last_collected_at,
            "safe_error_code": account.safe_error_code,
            "follower_count": latest.follower_count if latest else None,
            "latest_posts": latest.posts if latest else [],
        }

    def list_competitors(self) -> list[dict[str, object]]:
        require_permission(self._context.role, Permission.READ_CONTENT)
        accounts = self._session.scalars(
            select(CompetitorAccount)
            .where(CompetitorAccount.workspace_id == self._context.workspace_id)
            .order_by(CompetitorAccount.platform, CompetitorAccount.name)
        ).all()
        return [self.competitor_payload(account) for account in accounts]

    def collect_competitor(self, account_id: UUID) -> CompetitorAccount:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        account = self._session.scalar(
            select(CompetitorAccount).where(
                CompetitorAccount.id == account_id,
                CompetitorAccount.workspace_id == self._context.workspace_id,
            )
        )
        if account is None:
            raise LookupError("competitor account not found")
        latest = self._latest_competitor_observation(account.id)
        if latest is not None and latest.provider_fetched_at >= utc_now() - timedelta(
            minutes=10
        ):
            return account
        config = self._config()
        if config is None and not get_settings().app_mock_mode:
            raise LookupError("public data provider is not configured")
        if (
            config is not None
            and config.status is not ProviderConfigStatus.VERIFIED
            and not get_settings().app_mock_mode
        ):
            raise ValueError("请先完成 TikHub 连接测试")
        if config is not None:
            _reserve_provider_call(config)
        provider = (
            MockPublicDataProvider()
            if config is None
            else _provider_from_config(config)
        )
        try:
            result = provider.fetch_account_posts(
                platform=account.platform,
                platform_account_id=account.platform_account_id,
            )
        except PublicProviderError as error:
            account.status = BindingStatus.ERROR
            account.safe_error_code = error.code
            account.next_collection_at = utc_now() + timedelta(hours=1)
            self._session.flush()
            raise
        observation = CompetitorObservation(
            workspace_id=self._context.workspace_id,
            competitor_account_id=account.id,
            provider=provider.name,
            platform=account.platform,
            endpoint_contract=result.endpoint_contract,
            provider_fetched_at=result.fetched_at,
            received_at=utc_now(),
            raw_response=result.raw_response,
            raw_sha256=_raw_sha(result.raw_response),
            follower_count=(
                int(result.follower_count)
                if result.follower_count is not None
                else None
            ),
            posts=result.posts[:20],
        )
        self._session.add(observation)
        account.status = BindingStatus.ACTIVE
        account.last_collected_at = result.fetched_at
        account.next_collection_at = result.fetched_at + timedelta(
            hours=account.collection_interval_hours
        )
        account.safe_error_code = None
        self._session.flush()
        return account

    def analyze_comments(
        self,
        *,
        platform: Platform,
        public_url: str,
        platform_content_id: str | None,
    ) -> CommentDemandAnalysis:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        public_url = _valid_public_url(platform, public_url)
        if platform_content_id:
            cached = self._session.scalar(
                select(CommentDemandAnalysis)
                .where(
                    CommentDemandAnalysis.workspace_id == self._context.workspace_id,
                    CommentDemandAnalysis.platform == platform,
                    CommentDemandAnalysis.platform_content_id == platform_content_id,
                    CommentDemandAnalysis.received_at
                    >= utc_now() - timedelta(minutes=10),
                )
                .order_by(CommentDemandAnalysis.received_at.desc())
                .limit(1)
            )
            if cached is not None:
                return cached
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
        if config is not None and platform_content_id is None:
            _reserve_provider_call(config)
        resolved = provider.resolve_content(
            platform=platform,
            public_url=public_url,
            platform_content_id=platform_content_id,
        )
        cached = self._session.scalar(
            select(CommentDemandAnalysis)
            .where(
                CommentDemandAnalysis.workspace_id == self._context.workspace_id,
                CommentDemandAnalysis.platform == platform,
                CommentDemandAnalysis.platform_content_id
                == resolved.platform_content_id,
                CommentDemandAnalysis.received_at >= utc_now() - timedelta(minutes=10),
            )
            .order_by(CommentDemandAnalysis.received_at.desc())
            .limit(1)
        )
        if cached is not None:
            return cached
        if config is not None:
            _reserve_provider_call(config)
        result = provider.fetch_content_comments(
            platform=platform, locator=resolved.locator
        )
        themes, questions = _analyze_comment_texts(result.comments)
        analysis = CommentDemandAnalysis(
            workspace_id=self._context.workspace_id,
            platform=platform,
            public_url=resolved.public_url,
            platform_content_id=resolved.platform_content_id,
            provider=provider.name,
            endpoint_contract=result.endpoint_contract,
            provider_fetched_at=result.fetched_at,
            received_at=utc_now(),
            raw_response=result.raw_response,
            raw_sha256=_raw_sha(result.raw_response),
            comment_count=len(result.comments),
            themes=themes,
            top_questions=questions,
        )
        self._session.add(analysis)
        self._session.flush()
        return analysis

    @staticmethod
    def comment_payload(item: CommentDemandAnalysis) -> dict[str, object]:
        return {
            "id": item.id,
            "platform": item.platform.value,
            "public_url": item.public_url,
            "platform_content_id": item.platform_content_id,
            "provider": item.provider,
            "collected_at": item.provider_fetched_at,
            "comment_count": item.comment_count,
            "themes": item.themes,
            "top_questions": item.top_questions,
        }

    def list_comment_analyses(self) -> list[dict[str, object]]:
        require_permission(self._context.role, Permission.READ_CONTENT)
        items = self._session.scalars(
            select(CommentDemandAnalysis)
            .where(CommentDemandAnalysis.workspace_id == self._context.workspace_id)
            .order_by(CommentDemandAnalysis.received_at.desc())
            .limit(10)
        ).all()
        return [self.comment_payload(item) for item in items]

    @staticmethod
    def trend_search_payload(item: PublicTrendSearch) -> dict[str, object]:
        return {
            "id": item.id,
            "platform": item.platform.value,
            "keyword": item.keyword,
            "provider": item.provider,
            "collected_at": item.provider_fetched_at,
            "results": item.results,
        }

    def list_trend_searches(self) -> list[dict[str, object]]:
        require_permission(self._context.role, Permission.READ_CONTENT)
        items = self._session.scalars(
            select(PublicTrendSearch)
            .where(PublicTrendSearch.workspace_id == self._context.workspace_id)
            .order_by(PublicTrendSearch.received_at.desc())
            .limit(10)
        ).all()
        return [self.trend_search_payload(item) for item in items]

    def search_trends(
        self,
        *,
        platform: Platform,
        keyword: str,
    ) -> PublicTrendSearch:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        normalized_keyword = " ".join(keyword.split()).strip()
        if len(normalized_keyword) < 2:
            raise ValueError("搜索词至少需要 2 个字符")
        cached = self._session.scalar(
            select(PublicTrendSearch)
            .where(
                PublicTrendSearch.workspace_id == self._context.workspace_id,
                PublicTrendSearch.platform == platform,
                PublicTrendSearch.keyword == normalized_keyword,
                PublicTrendSearch.received_at >= utc_now() - timedelta(minutes=10),
            )
            .order_by(PublicTrendSearch.received_at.desc())
            .limit(1)
        )
        if cached is not None:
            return cached
        config = self._config()
        if config is None and not get_settings().app_mock_mode:
            raise LookupError("public data provider is not configured")
        if (
            config is not None
            and config.status is not ProviderConfigStatus.VERIFIED
            and not get_settings().app_mock_mode
        ):
            raise ValueError("请先完成 TikHub 连接测试")
        if config is not None:
            _reserve_provider_call(config)
        provider = (
            MockPublicDataProvider()
            if config is None
            else _provider_from_config(config)
        )
        result = provider.search_public_content(
            platform=platform,
            keyword=normalized_keyword,
        )
        search = PublicTrendSearch(
            workspace_id=self._context.workspace_id,
            platform=platform,
            keyword=normalized_keyword,
            provider=provider.name,
            endpoint_contract=result.endpoint_contract,
            provider_fetched_at=result.fetched_at,
            received_at=utc_now(),
            raw_response=result.raw_response,
            raw_sha256=_raw_sha(result.raw_response),
            results=result.results[:20],
        )
        self._session.add(search)
        self._session.flush()
        return search

    def report_payload(self) -> dict[str, object]:
        require_permission(self._context.role, Permission.READ_CONTENT)
        now = utc_now()
        since = now - timedelta(hours=24)
        accounts = list(
            self._session.scalars(
                select(CompetitorAccount).where(
                    CompetitorAccount.workspace_id == self._context.workspace_id,
                    CompetitorAccount.status != BindingStatus.DISABLED,
                )
            )
        )
        alerts: list[dict[str, object]] = []
        for account in accounts:
            latest = self._latest_competitor_observation(account.id)
            if latest is None or len(latest.posts) < 2:
                continue
            scores = [_engagement(post) for post in latest.posts]
            baseline = median(scores)
            for post, score in zip(latest.posts, scores, strict=True):
                if score >= 50 and score >= max(1, baseline * 2):
                    alerts.append(
                        {
                            "kind": "competitor_viral",
                            "platform": account.platform.value,
                            "title": str(post.get("title") or "对标账号高互动内容")[
                                :300
                            ],
                            "detail": f"互动量约为该账号近期中位数的 {score / max(1, baseline):.1f} 倍，建议复盘选题和表达结构。",
                            "public_url": (
                                str(post["public_url"])
                                if isinstance(post.get("public_url"), str)
                                else account.public_url
                            ),
                        }
                    )
        own_observations = list(
            self._session.scalars(
                select(PublicObservation)
                .where(
                    PublicObservation.workspace_id == self._context.workspace_id,
                    PublicObservation.received_at >= since,
                )
                .order_by(
                    PublicObservation.binding_id, PublicObservation.provider_fetched_at
                )
            )
        )
        by_binding: dict[UUID, list[PublicObservation]] = {}
        for item in own_observations:
            by_binding.setdefault(item.binding_id, []).append(item)
        for binding_id, observations in by_binding.items():
            if len(observations) < 2:
                continue
            previous, latest_public = observations[-2:]
            previous_score = _engagement(previous.normalized_metrics)
            latest_score = _engagement(latest_public.normalized_metrics)
            if latest_score - previous_score >= 50 and latest_score >= max(
                1, previous_score * 1.8
            ):
                binding = self._session.get(PublishedContentBinding, binding_id)
                if binding is not None:
                    alerts.append(
                        {
                            "kind": "own_growth",
                            "platform": binding.platform.value,
                            "title": "自己的作品互动正在加速",
                            "detail": "最近一次公开数据相较上次增长明显，建议及时查看评论并复用有效结构。",
                            "public_url": binding.public_url,
                        }
                    )
        comment_count = len(
            list(
                self._session.scalars(
                    select(CommentDemandAnalysis.id).where(
                        CommentDemandAnalysis.workspace_id
                        == self._context.workspace_id,
                        CommentDemandAnalysis.received_at >= since,
                    )
                )
            )
        )
        actions: list[str] = []
        if alerts:
            actions.append("先复盘预警内容，把有效选题或结构保存为创作参考。")
        if not accounts:
            actions.append("添加 1—3 个同赛道对标账号，建立每天可比较的观察样本。")
        if comment_count == 0:
            actions.append("选择一条近期作品分析评论，确认用户最常问的问题。")
        if not own_observations:
            actions.append("为已发布作品保存公开链接，开始自动回收数据。")
        if not actions:
            actions.append("数据采集正常，优先处理互动增长最快的内容和高频评论需求。")
        return {
            "generated_at": now,
            "own_updates_24h": len(own_observations),
            "monitored_accounts": len(accounts),
            "comment_analyses_24h": comment_count,
            "alerts": alerts[:20],
            "actions": actions,
        }


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


def run_competitor_collection(account_id: UUID) -> None:
    with SessionFactory() as session:
        account = session.get(CompetitorAccount, account_id)
        if account is None or account.status is BindingStatus.DISABLED:
            return
        context = WorkspaceContext(
            workspace_id=account.workspace_id,
            member_id=None,
            role="admin",
        )
        try:
            PublicDataService(session, context).collect_competitor(account.id)
        except (LookupError, PublicProviderError, ValueError) as error:
            account.status = BindingStatus.ERROR
            account.safe_error_code = (
                error.code
                if isinstance(error, PublicProviderError)
                else "PUBLIC_PROVIDER_CONFIGURATION_REQUIRED"
            )
            account.next_collection_at = utc_now() + timedelta(hours=1)
            session.commit()
            return
        session.commit()


def run_due_competitor_collections(*, limit: int = 10) -> int:
    now = utc_now()
    with SessionFactory() as session:
        account_ids = list(
            session.scalars(
                select(CompetitorAccount.id)
                .where(
                    CompetitorAccount.status.in_(
                        [BindingStatus.ACTIVE, BindingStatus.ERROR]
                    ),
                    CompetitorAccount.next_collection_at <= now,
                )
                .order_by(CompetitorAccount.next_collection_at, CompetitorAccount.id)
                .limit(limit)
            )
        )
    for account_id in account_ids:
        run_competitor_collection(account_id)
    return len(account_ids)
