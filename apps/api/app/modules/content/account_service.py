import math
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import WorkspaceContext
from app.modules.content.account_models import (
    BenchmarkProfile,
    ColumnCampaign,
    ColumnCampaignKind,
    ObjectiveProfile,
    Platform,
    PlatformAccount,
)
from app.modules.workspace.permissions import Permission, require_permission


@dataclass(frozen=True)
class EffectiveConfiguration:
    objective_profile: ObjectiveProfile
    benchmark_profile: BenchmarkProfile
    source: str


class AccountConfigurationService:
    def __init__(self, session: Session, context: WorkspaceContext) -> None:
        self._session = session
        self._context = context

    @staticmethod
    def normalize_weights(weights: dict[str, float]) -> dict[str, float]:
        if not weights or any(
            not key.strip() or not math.isfinite(value) or value <= 0
            for key, value in weights.items()
        ):
            raise ValueError("enabled metric weights must be positive finite numbers")
        total = sum(weights.values())
        items = list(weights.items())
        normalized = {
            key: round(value / total, 10) for key, value in items[:-1]
        }
        last_key, _ = items[-1]
        normalized[last_key] = round(1 - sum(normalized.values()), 10)
        return normalized

    def _account(self, account_id: UUID) -> PlatformAccount:
        account = self._session.scalar(
            select(PlatformAccount).where(
                PlatformAccount.id == account_id,
                PlatformAccount.workspace_id == self._context.workspace_id,
            )
        )
        if account is None:
            raise LookupError("account not found")
        return account

    def _column_campaign(self, account_id: UUID, item_id: UUID) -> ColumnCampaign:
        self._account(account_id)
        item = self._session.scalar(
            select(ColumnCampaign).where(
                ColumnCampaign.id == item_id,
                ColumnCampaign.account_id == account_id,
                ColumnCampaign.workspace_id == self._context.workspace_id,
            )
        )
        if item is None:
            raise LookupError("column or campaign not found")
        return item

    def _next_version(self, model: type[ObjectiveProfile] | type[BenchmarkProfile], account_id: UUID) -> int:
        current = self._session.scalar(select(func.max(model.version)).where(model.account_id == account_id))
        return int(current or 0) + 1

    def _create_objective_profile(
        self,
        account: PlatformAccount,
        objectives: list[str],
        metric_weights: dict[str, float],
        *,
        is_account_default: bool,
    ) -> ObjectiveProfile:
        if not objectives or len(objectives) != len(set(objectives)):
            raise ValueError("objectives must be non-empty and unique")
        profile = ObjectiveProfile(
            workspace_id=self._context.workspace_id,
            account_id=account.id,
            version=self._next_version(ObjectiveProfile, account.id),
            objectives=objectives,
            metric_weights=self.normalize_weights(metric_weights),
            is_account_default=is_account_default,
        )
        self._session.add(profile)
        self._session.flush()
        return profile

    def _create_benchmark_profile(
        self,
        account: PlatformAccount,
        sample_size: int,
        *,
        is_account_default: bool,
    ) -> BenchmarkProfile:
        if not 1 <= sample_size <= 500:
            raise ValueError("benchmark sample size must be between 1 and 500")
        profile = BenchmarkProfile(
            workspace_id=self._context.workspace_id,
            account_id=account.id,
            version=self._next_version(BenchmarkProfile, account.id),
            sample_size=sample_size,
            is_account_default=is_account_default,
        )
        self._session.add(profile)
        self._session.flush()
        return profile

    def create_account(
        self,
        platform: Platform,
        name: str,
        objectives: list[str],
        metric_weights: dict[str, float],
        benchmark_sample_size: int,
    ) -> tuple[PlatformAccount, ObjectiveProfile, BenchmarkProfile]:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        account = PlatformAccount(
            workspace_id=self._context.workspace_id,
            platform=platform,
            name=name,
        )
        self._session.add(account)
        self._session.flush()
        objective = self._create_objective_profile(
            account, objectives, metric_weights, is_account_default=True
        )
        benchmark = self._create_benchmark_profile(
            account, benchmark_sample_size, is_account_default=True
        )
        return account, objective, benchmark

    def list_accounts(self) -> list[PlatformAccount]:
        require_permission(self._context.role, Permission.READ_CONTENT)
        return list(
            self._session.scalars(
                select(PlatformAccount)
                .where(PlatformAccount.workspace_id == self._context.workspace_id)
                .order_by(PlatformAccount.created_at)
            )
        )

    def rename_account(self, account_id: UUID, name: str) -> PlatformAccount:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        account = self._account(account_id)
        account.name = name
        self._session.flush()
        return account

    def delete_account(self, account_id: UUID) -> None:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        self._session.delete(self._account(account_id))
        self._session.flush()

    def update_configuration(
        self,
        account_id: UUID,
        objectives: list[str],
        metric_weights: dict[str, float],
        benchmark_sample_size: int,
    ) -> tuple[PlatformAccount, ObjectiveProfile, BenchmarkProfile]:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        account = self._account(account_id)
        objective = self._create_objective_profile(
            account, objectives, metric_weights, is_account_default=True
        )
        benchmark = self._create_benchmark_profile(
            account, benchmark_sample_size, is_account_default=True
        )
        return account, objective, benchmark

    def create_column_campaign(
        self,
        account_id: UUID,
        *,
        name: str,
        kind: ColumnCampaignKind,
        starts_at: datetime | None,
        ends_at: datetime | None,
        objectives: list[str] | None,
        metric_weights: dict[str, float] | None,
        benchmark_sample_size: int | None,
    ) -> ColumnCampaign:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        account = self._account(account_id)
        if starts_at is not None and ends_at is not None and ends_at <= starts_at:
            raise ValueError("ends_at must be after starts_at")
        objective = None
        benchmark = None
        if objectives is not None or metric_weights is not None:
            if objectives is None or metric_weights is None:
                raise ValueError("objectives and metric_weights must be provided together")
            objective = self._create_objective_profile(
                account, objectives, metric_weights, is_account_default=False
            )
        if benchmark_sample_size is not None:
            benchmark = self._create_benchmark_profile(
                account, benchmark_sample_size, is_account_default=False
            )
        column_campaign = ColumnCampaign(
            workspace_id=self._context.workspace_id,
            account_id=account.id,
            name=name,
            kind=kind,
            starts_at=starts_at,
            ends_at=ends_at,
            objective_profile_id=objective.id if objective else None,
            benchmark_profile_id=benchmark.id if benchmark else None,
        )
        self._session.add(column_campaign)
        self._session.flush()
        return column_campaign

    def list_column_campaigns(self, account_id: UUID) -> list[ColumnCampaign]:
        require_permission(self._context.role, Permission.READ_CONTENT)
        account = self._account(account_id)
        return list(
            self._session.scalars(
                select(ColumnCampaign)
                .where(ColumnCampaign.account_id == account.id)
                .order_by(ColumnCampaign.created_at)
            )
        )

    def restore_column_campaign_defaults(
        self, account_id: UUID, item_id: UUID
    ) -> ColumnCampaign:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        item = self._column_campaign(account_id, item_id)
        item.objective_profile_id = None
        item.benchmark_profile_id = None
        self._session.flush()
        return item

    def delete_column_campaign(self, account_id: UUID, item_id: UUID) -> None:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        self._session.delete(self._column_campaign(account_id, item_id))
        self._session.flush()

    def _latest_default(self, model: type[ObjectiveProfile] | type[BenchmarkProfile], account_id: UUID):
        return self._session.scalar(
            select(model)
            .where(model.account_id == account_id, model.is_account_default.is_(True))
            .order_by(model.version.desc())
            .limit(1)
        )

    def effective_configuration(
        self,
        account_id: UUID,
        *,
        column_campaign_id: UUID | None = None,
        at: datetime,
    ) -> EffectiveConfiguration:
        require_permission(self._context.role, Permission.READ_CONTENT)
        account = self._account(account_id)
        objective = self._latest_default(ObjectiveProfile, account.id)
        benchmark = self._latest_default(BenchmarkProfile, account.id)
        if objective is None or benchmark is None:
            raise LookupError("account configuration not found")
        source = "account_default"
        if column_campaign_id is not None:
            item = self._session.scalar(
                select(ColumnCampaign).where(
                    ColumnCampaign.id == column_campaign_id,
                    ColumnCampaign.account_id == account.id,
                    ColumnCampaign.workspace_id == self._context.workspace_id,
                )
            )
            if item is None:
                raise LookupError("column or campaign not found")
            active = (item.starts_at is None or item.starts_at <= at) and (
                item.ends_at is None or item.ends_at >= at
            )
            if active:
                overridden = False
                if item.objective_profile_id is not None:
                    objective = self._session.get(ObjectiveProfile, item.objective_profile_id)
                    overridden = True
                if item.benchmark_profile_id is not None:
                    benchmark = self._session.get(BenchmarkProfile, item.benchmark_profile_id)
                    overridden = True
                if overridden:
                    source = f"{item.kind.value}_override"
        return EffectiveConfiguration(objective, benchmark, source)

    def versions(self, account_id: UUID) -> tuple[list[ObjectiveProfile], list[BenchmarkProfile]]:
        require_permission(self._context.role, Permission.READ_CONTENT)
        account = self._account(account_id)
        objectives = list(
            self._session.scalars(
                select(ObjectiveProfile)
                .where(ObjectiveProfile.account_id == account.id, ObjectiveProfile.is_account_default.is_(True))
                .order_by(ObjectiveProfile.version)
            )
        )
        benchmarks = list(
            self._session.scalars(
                select(BenchmarkProfile)
                .where(BenchmarkProfile.account_id == account.id, BenchmarkProfile.is_account_default.is_(True))
                .order_by(BenchmarkProfile.version)
            )
        )
        return objectives, benchmarks
