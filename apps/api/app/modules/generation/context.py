import hashlib
import json
from collections.abc import Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import WorkspaceContext
from app.modules.analysis.viral_models import (
    ViralCandidate,
    ViralCandidateStatus,
    ViralLibraryItem,
)
from app.modules.content.account_models import (
    ColumnCampaign,
    PlatformAccount,
)
from app.modules.content.models import Content, ContentStatus
from app.modules.generation.schemas import (
    ConfirmedFactSnapshot,
    GenerationContext,
    GenerationInputs,
    GenerationRun,
    ModelSnapshot,
    SourceAssetSnapshot,
    StyleSnapshot,
    ViralReferenceSnapshot,
)
from app.modules.models.models import ModelConfig, ModelConfigStatus
from app.modules.models.capabilities import Capability
from app.modules.models.catalog import get_catalog_entry
from app.modules.style_facts.fact_models import (
    FactConflictStatus,
    FactItem,
    FactItemStatus,
    FactSource,
)
from app.modules.style_facts.fact_policy import (
    FactUseDisposition,
    classify_fact_use,
)
from app.modules.style_facts.style_models import (
    AccountStyleProfile,
    StyleProfileStatus,
)
from app.modules.style_facts.style_service import (
    StyleInheritanceSwitches,
    StyleProfileService,
)
from app.modules.workspace.permissions import Permission, require_permission


def _ordered_rows[T](
    selected_ids: tuple[UUID, ...],
    rows: list[T],
    *,
    id_of: Callable[[T], UUID],
) -> list[T]:
    by_id = {id_of(row): row for row in rows}
    try:
        return [by_id[item_id] for item_id in selected_ids]
    except KeyError as error:
        raise ValueError("selected reference is not generation eligible") from error


class GenerationContextBuilder:
    def __init__(self, session: Session, context: WorkspaceContext) -> None:
        self._session = session
        self._workspace = context

    def _account(self, inputs: GenerationInputs) -> PlatformAccount:
        account = self._session.scalar(
            select(PlatformAccount).where(
                PlatformAccount.id == inputs.account_id,
                PlatformAccount.workspace_id == self._workspace.workspace_id,
            )
        )
        if account is None or account.platform is not inputs.platform:
            raise ValueError("account is not generation eligible")
        return account

    def _column(self, inputs: GenerationInputs) -> None:
        if inputs.column_campaign_id is None:
            return
        column = self._session.scalar(
            select(ColumnCampaign).where(
                ColumnCampaign.id == inputs.column_campaign_id,
                ColumnCampaign.workspace_id == self._workspace.workspace_id,
                ColumnCampaign.account_id == inputs.account_id,
            )
        )
        if column is None:
            raise ValueError("column or campaign is not generation eligible")

    def _facts(
        self,
        inputs: GenerationInputs,
    ) -> tuple[tuple[ConfirmedFactSnapshot, ...], str]:
        if not inputs.confirmed_fact_item_ids:
            empty_version = hashlib.sha256(b"[]").hexdigest()
            return (), empty_version
        rows = list(
            self._session.execute(
                select(FactItem, FactSource)
                .join(FactSource, FactSource.id == FactItem.source_id)
                .where(FactItem.id.in_(inputs.confirmed_fact_item_ids))
            ).all()
        )
        by_id = {item.id: (item, source) for item, source in rows}
        snapshots: list[ConfirmedFactSnapshot] = []
        for item_id in sorted(inputs.confirmed_fact_item_ids, key=str):
            pair = by_id.get(item_id)
            if pair is None:
                raise ValueError("selected fact is not generation eligible")
            item, source = pair
            if (
                item.workspace_id != self._workspace.workspace_id
                or source.workspace_id != self._workspace.workspace_id
                or item.status is not FactItemStatus.CONFIRMED
                or item.confirmed_at is None
                or item.conflict_status is FactConflictStatus.UNRESOLVED
                or classify_fact_use(item.field_code, source.level).disposition
                is FactUseDisposition.CANDIDATE_ONLY
            ):
                raise ValueError("selected fact is not generation eligible")
            snapshots.append(
                ConfirmedFactSnapshot(
                    item_id=item.id,
                    field_code=item.field_code,
                    value=item.value,
                    source_id=source.id,
                    source_level=source.level.value,
                )
            )
        payload = json.dumps(
            [snapshot.model_dump(mode="json") for snapshot in snapshots],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return tuple(snapshots), hashlib.sha256(payload).hexdigest()

    def _style(self, inputs: GenerationInputs) -> StyleSnapshot | None:
        if inputs.style_profile_id is None:
            if any(
                (
                    inputs.style_switches.title,
                    inputs.style_switches.copy_style,
                    inputs.style_switches.cover,
                )
            ):
                raise ValueError("enabled style inheritance requires a profile")
            return None
        profile = self._session.scalar(
            select(AccountStyleProfile).where(
                AccountStyleProfile.id == inputs.style_profile_id,
                AccountStyleProfile.workspace_id == self._workspace.workspace_id,
                AccountStyleProfile.account_id == inputs.account_id,
                AccountStyleProfile.status == StyleProfileStatus.CONFIRMED,
                AccountStyleProfile.confirmed_at.is_not(None),
            )
        )
        if profile is None:
            raise ValueError("style profile is not generation eligible")
        expected_scope = (
            "account"
            if profile.column_campaign_id is None
            else f"column:{profile.column_campaign_id}"
        )
        if profile.scope_key != expected_scope or (
            profile.column_campaign_id is not None
            and profile.column_campaign_id != inputs.column_campaign_id
        ):
            raise ValueError("style profile is not generation eligible")
        switches = StyleInheritanceSwitches(
            title=inputs.style_switches.title,
            copy=inputs.style_switches.copy_style,
            cover=inputs.style_switches.cover,
        )
        filtered = StyleProfileService.filtered_style(profile, switches)
        return StyleSnapshot(
            profile_id=profile.id,
            version=profile.version,
            switches=inputs.style_switches,
            style_json=json.dumps(
                filtered,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )

    def _viral_references(
        self,
        inputs: GenerationInputs,
    ) -> tuple[ViralReferenceSnapshot, ...]:
        if not inputs.viral_library_item_ids:
            return ()
        rows = list(
            self._session.execute(
                select(ViralLibraryItem, Content, ViralCandidate)
                .join(Content, Content.id == ViralLibraryItem.content_id)
                .join(
                    ViralCandidate,
                    ViralCandidate.id == ViralLibraryItem.candidate_id,
                )
                .where(
                    ViralLibraryItem.id.in_(inputs.viral_library_item_ids)
                )
            ).all()
        )
        ordered = _ordered_rows(
            inputs.viral_library_item_ids,
            rows,
            id_of=lambda row: row[0].id,
        )
        snapshots: list[ViralReferenceSnapshot] = []
        for item, content, candidate in ordered:
            if (
                item.workspace_id != self._workspace.workspace_id
                or content.workspace_id != self._workspace.workspace_id
                or candidate.workspace_id != self._workspace.workspace_id
                or item.account_id != inputs.account_id
                or content.account_id != inputs.account_id
                or candidate.account_id != inputs.account_id
                or content.platform is not inputs.platform
                or candidate.platform is not inputs.platform
                or candidate.content_id != content.id
                or candidate.status is not ViralCandidateStatus.CONFIRMED
                or item.confirmed_at is None
                or item.revoked_at is not None
                or content.deleted_at is not None
                or content.status is not ContentStatus.PUBLISHED
            ):
                raise ValueError(
                    "selected viral reference is not generation eligible"
                )
            snapshots.append(
                ViralReferenceSnapshot(
                    library_item_id=item.id,
                    content_id=content.id,
                    category=item.category.value,
                    strategy_tags=tuple(item.strategy_tags),
                    applicable_scenarios=tuple(item.applicable_scenarios),
                    structure_summary=item.structure_summary,
                )
            )
        return tuple(snapshots)

    def _assets(
        self,
        inputs: GenerationInputs,
    ) -> tuple[SourceAssetSnapshot, ...]:
        if not inputs.source_asset_ids:
            return ()
        rows = list(
            self._session.scalars(
                select(FactSource).where(
                    FactSource.id.in_(inputs.source_asset_ids),
                    FactSource.workspace_id == self._workspace.workspace_id,
                )
            )
        )
        ordered = _ordered_rows(
            inputs.source_asset_ids,
            rows,
            id_of=lambda source: source.id,
        )
        snapshots: list[SourceAssetSnapshot] = []
        for source in ordered:
            if not source.content_sha256:
                raise ValueError("source asset is not generation eligible")
            snapshots.append(
                SourceAssetSnapshot(
                    source_id=source.id,
                    kind=source.kind.value,
                    content_sha256=source.content_sha256,
                    status=source.status.value,
                    file_name=source.file_name,
                    mime_type=source.mime_type,
                    source_url=source.source_url,
                )
            )
        return tuple(snapshots)

    def _model(self, inputs: GenerationInputs) -> ModelSnapshot:
        config = self._session.scalar(
            select(ModelConfig).where(
                ModelConfig.id == inputs.model_config_id,
                ModelConfig.workspace_id == self._workspace.workspace_id,
            )
        )
        if config is None or config.status is ModelConfigStatus.INCOMPATIBLE:
            raise ValueError("model config is not generation eligible")
        contract_version = "mock-structured-v1"
        if config.provider == "qianwen":
            try:
                catalog = get_catalog_entry(config.provider, config.model_id)
            except LookupError as error:
                raise ValueError(
                    "model config is not generation eligible"
                ) from error
            if (
                set(config.capabilities)
                != {capability.value for capability in catalog.capabilities}
                or config.status.value != catalog.adapter_status.value
            ):
                raise ValueError("model config is not generation eligible")
            contract_version = catalog.contract_version
        elif config.provider == "openai_compatible":
            if (
                set(config.capabilities) != {Capability.TEXT.value}
                or config.status is not ModelConfigStatus.COMMUNITY
            ):
                raise ValueError("model config is not generation eligible")
            contract_version = "openai-compatible-chat-json-v1"
        return ModelSnapshot(
            config_id=config.id,
            provider=config.provider,
            model_id=config.model_id,
            capabilities=tuple(sorted(config.capabilities)),
            status=config.status.value,
            contract_version=contract_version,
            configuration_version=config.updated_at.isoformat(),
        )

    def create_run(self, inputs: GenerationInputs) -> GenerationRun:
        require_permission(self._workspace.role, Permission.READ_CONTENT)
        self._account(inputs)
        self._column(inputs)
        facts, facts_version = self._facts(inputs)
        context = GenerationContext(
            workspace_id=self._workspace.workspace_id,
            account_id=inputs.account_id,
            platform=inputs.platform,
            column_campaign_id=inputs.column_campaign_id,
            target=inputs.target,
            confirmed_facts=facts,
            confirmed_facts_version=facts_version,
            style=self._style(inputs),
            viral_references=self._viral_references(inputs),
            user_prompt=inputs.user_prompt,
            source_assets=self._assets(inputs),
            risk_rule_version=inputs.risk_rule_version,
            model=self._model(inputs),
        )
        return GenerationRun(context=context)

    def retry(self, run: GenerationRun) -> GenerationRun:
        require_permission(self._workspace.role, Permission.READ_CONTENT)
        if run.context.workspace_id != self._workspace.workspace_id:
            raise ValueError("generation run belongs to another workspace")
        return GenerationRun(
            context=run.context,
            retry_of_run_id=run.id,
        )
