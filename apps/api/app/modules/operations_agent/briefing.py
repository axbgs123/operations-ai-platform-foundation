from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.observability import OperationalTask, SQLAlchemyOperationsStore
from app.core.security import WorkspaceContext
from app.modules.analysis.models import (
    AnalysisRun,
    ProductEvent,
    ProductEventOutbox,
)
from app.modules.content.account_models import (
    BenchmarkProfile,
    ColumnCampaign,
    ObjectiveProfile,
    Platform,
    PlatformAccount,
)
from app.modules.content.models import Content
from app.modules.imports.models import ImportBatch, ImportBatchStatus
from app.modules.metrics.models import DataSnapshot
from app.modules.models.models import ModelConfig
from app.modules.operations_agent.models import AgentBriefing, AgentEvent
from app.modules.operations_agent.schemas import (
    BriefingCandidateRead,
    CandidateKind,
    DailyBriefingRead,
)
from app.modules.risk_rag.models import RiskScan
from app.modules.workbench.schemas import AnalysisQueueItem, PreflightQueueItem
from app.modules.workbench.service import WorkbenchService
from app.modules.workspace.models import Workspace


BRIEFING_ALGORITHM_VERSION = "operations-briefing-v1"
TOOL_CATALOG_VERSION = "operations-agent-tools-v1"
_FAILED_TASK_STATUSES = frozenset(
    {"failed", "dead_letter", "compensation_required"}
)
_SECURITY_TASK_ERROR_CODES = frozenset(
    {
        "AUTHORIZATION_FAILED",
        "PERMISSION_DENIED",
        "WORKSPACE_ACCESS_REVOKED",
    }
)
_UNSUPPRESSIBLE_KINDS = frozenset(
    {
        CandidateKind.HIGH_RISK_BLOCKED,
        CandidateKind.PERMISSION_SECURITY_FAILURE,
    }
)


@dataclass(frozen=True)
class BriefingCandidate:
    kind: CandidateKind
    workspace_id: UUID
    platform: Platform
    account_id: UUID
    content_id: UUID | None
    blocking_rank: int
    severity_rank: int
    evidence_rank: int
    objective_rank: int
    executable_rank: int
    repeat_penalty: int
    evidence_refs: tuple[str, ...]
    safe_title: str
    safe_reason: str

    @property
    def candidate_id(self) -> str:
        canonical = {
            "workspace_id": str(self.workspace_id),
            "kind": self.kind.value,
            "platform": self.platform.value,
            "account_id": str(self.account_id),
            "content_id": (
                str(self.content_id) if self.content_id is not None else None
            ),
            "evidence_refs": list(self.evidence_refs),
        }
        encoded = json.dumps(
            canonical,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    @property
    def sort_key(
        self,
    ) -> tuple[int, int, int, int, int, int, str, str, str]:
        return (
            self.repeat_penalty,
            -self.blocking_rank,
            -self.severity_rank,
            -self.evidence_rank,
            -self.objective_rank,
            -self.executable_rank,
            str(self.account_id),
            self.kind.value,
            str(self.content_id or ""),
        )

    def to_read(self, *, is_primary: bool) -> BriefingCandidateRead:
        return BriefingCandidateRead(
            candidate_id=self.candidate_id,
            kind=self.kind,
            platform=self.platform,
            account_id=self.account_id,
            content_id=self.content_id,
            is_primary=is_primary,
            safe_title=self.safe_title,
            safe_reason=self.safe_reason,
            blocking_rank=self.blocking_rank,
            severity_rank=self.severity_rank,
            evidence_rank=self.evidence_rank,
            objective_rank=self.objective_rank,
            executable_rank=self.executable_rank,
            repeat_penalty=self.repeat_penalty,
            evidence_refs=self.evidence_refs,
        )


class BriefingService:
    def __init__(self, session: Session, context: WorkspaceContext) -> None:
        if context.member_id is None or context.role == "demo":
            raise PermissionError("private operations agent unavailable")
        self._session = session
        self._context = context
        self._workbench = WorkbenchService(session, context)

    def generate(self, *, force: bool = False) -> DailyBriefingRead:
        del force
        state, data_cutoff_at, tasks, import_batches = self._input_state()
        suppressed_kinds, deferred_candidate_ids = self._preferences()
        fingerprint = self._state_fingerprint(
            state=state,
            suppressed_kinds=suppressed_kinds,
            deferred_candidate_ids=deferred_candidate_ids,
        )
        existing = self._session.scalar(
            select(AgentBriefing).where(
                AgentBriefing.workspace_id == self._context.workspace_id,
                AgentBriefing.input_fingerprint == fingerprint,
                AgentBriefing.algorithm_version
                == BRIEFING_ALGORITHM_VERSION,
            )
        )
        if existing is not None:
            return self._read(existing)

        candidates = [
            candidate
            for candidate in self._build_candidates(tasks, import_batches)
            if (
                candidate.kind not in suppressed_kinds
                or candidate.kind in _UNSUPPRESSIBLE_KINDS
            )
        ]
        candidates = [
            replace(
                candidate,
                repeat_penalty=(
                    candidate.repeat_penalty + 100
                    if candidate.candidate_id in deferred_candidate_ids
                    else candidate.repeat_penalty
                ),
            )
            for candidate in candidates
        ]
        candidates.sort(key=lambda item: item.sort_key)
        reads = tuple(
            candidate.to_read(is_primary=index == 0)
            for index, candidate in enumerate(candidates)
        )
        primary = reads[0] if reads else None
        briefing = AgentBriefing(
            workspace_id=self._context.workspace_id,
            input_fingerprint=fingerprint,
            algorithm_version=BRIEFING_ALGORITHM_VERSION,
            tool_catalog_version=TOOL_CATALOG_VERSION,
            candidates=[
                item.model_dump(mode="json")
                for item in reads
            ],
            priority_candidate=(
                primary.model_dump(mode="json")
                if primary is not None
                else None
            ),
            data_cutoff_at=data_cutoff_at,
        )
        try:
            with self._session.begin_nested():
                self._session.add(briefing)
                self._session.flush()
        except IntegrityError:
            concurrent = self._session.scalar(
                select(AgentBriefing).where(
                    AgentBriefing.workspace_id
                    == self._context.workspace_id,
                    AgentBriefing.input_fingerprint == fingerprint,
                    AgentBriefing.algorithm_version
                    == BRIEFING_ALGORITHM_VERSION,
                )
            )
            if concurrent is None:
                raise
            return self._read(concurrent)
        return self._read(briefing)

    def current_input_fingerprint(
        self,
        *,
        excluded_analysis_ids: frozenset[UUID] = frozenset(),
        excluded_generation_ids: frozenset[UUID] = frozenset(),
        excluded_scan_ids: frozenset[UUID] = frozenset(),
        excluded_export_ids: frozenset[UUID] = frozenset(),
    ) -> str:
        state, _, _, _ = self._input_state(
            excluded_analysis_ids=excluded_analysis_ids,
            excluded_generation_ids=excluded_generation_ids,
            excluded_scan_ids=excluded_scan_ids,
            excluded_export_ids=excluded_export_ids,
        )
        suppressed_kinds, deferred_candidate_ids = self._preferences()
        return self._state_fingerprint(
            state=state,
            suppressed_kinds=suppressed_kinds,
            deferred_candidate_ids=deferred_candidate_ids,
        )

    def _state_fingerprint(
        self,
        *,
        state: dict[str, object],
        suppressed_kinds: set[CandidateKind],
        deferred_candidate_ids: set[str],
    ) -> str:
        return self._fingerprint(
            {
                "state": state,
                "member_id": str(self._context.member_id),
                "suppressed_kinds": sorted(
                    kind.value for kind in suppressed_kinds
                ),
                "deferred_candidate_ids": sorted(deferred_candidate_ids),
                "algorithm_version": BRIEFING_ALGORITHM_VERSION,
                "tool_catalog_version": TOOL_CATALOG_VERSION,
            }
        )

    def record_refresh(self, *, idempotency_key: str) -> DailyBriefingRead:
        self._append_idempotent_event(
            event_type="briefing_refresh_requested",
            idempotency_key=idempotency_key,
            safe_payload={"request": "refresh"},
        )
        return self.generate(force=True)

    def record_decision(
        self,
        briefing_id: UUID,
        *,
        decision: Literal["defer", "suppress_kind"],
        candidate_kind: CandidateKind | None,
        idempotency_key: str,
    ) -> DailyBriefingRead:
        briefing = self._session.scalar(
            select(AgentBriefing).where(
                AgentBriefing.id == briefing_id,
                AgentBriefing.workspace_id == self._context.workspace_id,
            )
        )
        if briefing is None:
            raise LookupError("briefing not found")
        primary = (
            BriefingCandidateRead.model_validate(
                briefing.priority_candidate
            )
            if briefing.priority_candidate is not None
            else None
        )
        candidates = tuple(
            BriefingCandidateRead.model_validate(item)
            for item in briefing.candidates
        )
        if decision == "defer":
            if candidate_kind is not None:
                raise ValueError("candidate_kind must be omitted for defer")
            if primary is None:
                raise ValueError("briefing has no candidate to defer")
            selected_kind = primary.kind
            selected_candidate_id = primary.candidate_id
        else:
            if candidate_kind is None:
                raise ValueError(
                    "candidate_kind is required for suppress_kind"
                )
            if candidate_kind in _UNSUPPRESSIBLE_KINDS:
                raise ValueError(
                    f"{candidate_kind.value} cannot be suppressed"
                )
            if candidate_kind not in {item.kind for item in candidates}:
                raise ValueError("candidate kind is not present in briefing")
            selected_kind = candidate_kind
            selected_candidate_id = None
        self._append_idempotent_event(
            event_type="briefing_decision",
            idempotency_key=idempotency_key,
            safe_payload={
                "briefing_id": str(briefing.id),
                "decision": decision,
                "candidate_kind": selected_kind.value,
                "candidate_id": selected_candidate_id,
            },
        )
        return self.generate(force=True)

    def _append_idempotent_event(
        self,
        *,
        event_type: str,
        idempotency_key: str,
        safe_payload: dict[str, object],
    ) -> AgentEvent:
        if not idempotency_key.strip() or len(idempotency_key) > 200:
            raise ValueError("invalid idempotency key")
        existing = self._session.scalar(
            select(AgentEvent).where(
                AgentEvent.workspace_id == self._context.workspace_id,
                AgentEvent.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if (
                existing.event_type != event_type
                or existing.actor_id != self._context.member_id
                or existing.safe_payload != safe_payload
            ):
                raise ValueError("idempotency key conflict")
            return existing
        event = AgentEvent(
            workspace_id=self._context.workspace_id,
            event_type=event_type,
            idempotency_key=idempotency_key,
            safe_payload=safe_payload,
            actor_id=self._context.member_id,
        )
        self._session.add(event)
        self._session.flush()
        return event

    def _preferences(
        self,
    ) -> tuple[set[CandidateKind], set[str]]:
        events = self._session.scalars(
            select(AgentEvent)
            .where(
                AgentEvent.workspace_id == self._context.workspace_id,
                AgentEvent.actor_id == self._context.member_id,
                AgentEvent.event_type == "briefing_decision",
            )
            .order_by(AgentEvent.created_at, AgentEvent.id)
        )
        suppressed: set[CandidateKind] = set()
        deferred: set[str] = set()
        for event in events:
            decision = event.safe_payload.get("decision")
            raw_kind = event.safe_payload.get("candidate_kind")
            if decision == "suppress_kind" and isinstance(raw_kind, str):
                try:
                    kind = CandidateKind(raw_kind)
                except ValueError:
                    continue
                if kind not in _UNSUPPRESSIBLE_KINDS:
                    suppressed.add(kind)
            candidate_id = event.safe_payload.get("candidate_id")
            if decision == "defer" and isinstance(candidate_id, str):
                deferred.add(candidate_id)
        return suppressed, deferred

    def _build_candidates(
        self,
        tasks: list[OperationalTask],
        import_batches: list[ImportBatch],
    ) -> list[BriefingCandidate]:
        context_read = self._workbench.context()
        overview = self._workbench.overview()
        cards = {card.account_id: card for card in overview.accounts}
        accounts_by_id = {
            account.account_id: account for account in context_read.accounts
        }
        candidates: list[BriefingCandidate] = []
        for batch in import_batches:
            if batch.status is not ImportBatchStatus.PREVIEW:
                continue
            account = accounts_by_id.get(batch.account_id)
            if account is None or account.platform != batch.platform.value:
                continue
            candidates.append(
                self._candidate(
                    kind=CandidateKind.IMPORT_WAITING_CONFIRMATION,
                    platform=batch.platform,
                    account_id=batch.account_id,
                    content_id=None,
                    ranks=(4, 2, 4, 3, 4),
                    evidence_refs=(f"import_batch:{batch.id}",),
                )
            )
        for account in context_read.accounts:
            platform = Platform(account.platform)
            for preflight_item in self._all_preflight_items(
                platform,
                account.account_id,
            ):
                candidate = self._preflight_candidate(
                    platform=platform,
                    account_id=account.account_id,
                    item=preflight_item,
                )
                if candidate is not None:
                    candidates.append(candidate)
            for analysis_item in self._all_analysis_items(
                platform,
                account.account_id,
            ):
                candidate = self._analysis_candidate(
                    platform=platform,
                    account_id=account.account_id,
                    item=analysis_item,
                )
                if candidate is not None:
                    candidates.append(candidate)
            card = cards[account.account_id]
            if (
                card.confirmed_snapshot_count == 0
                or card.completeness.score < 1
            ):
                candidates.append(
                    self._candidate(
                        kind=CandidateKind.INCOMPLETE_DATA,
                        platform=platform,
                        account_id=account.account_id,
                        content_id=None,
                        ranks=(2, 1, 2, 2, 3),
                        evidence_refs=(
                            f"account:{account.account_id}",
                            (
                                "snapshot:none"
                                if card.confirmed_snapshot_count == 0
                                else "profile:incomplete"
                            ),
                        ),
                    )
                )
        for task in tasks:
            if task.status not in _FAILED_TASK_STATUSES:
                continue
            account_id = self._failed_task_account_id(
                task,
                sole_account_id=(
                    context_read.accounts[0].account_id
                    if len(context_read.accounts) == 1
                    else None
                ),
            )
            task_account = (
                accounts_by_id.get(account_id)
                if account_id is not None
                else None
            )
            if task_account is None:
                continue
            candidates.append(
                self._candidate(
                    kind=(
                        CandidateKind.PERMISSION_SECURITY_FAILURE
                        if task.error_code in _SECURITY_TASK_ERROR_CODES
                        else CandidateKind.FAILED_TASK
                    ),
                    platform=Platform(task_account.platform),
                    account_id=task_account.account_id,
                    content_id=None,
                    ranks=(4, 3, 4, 2, 2),
                    evidence_refs=(
                        f"task:{task.task_type}:{task.task_id}",
                        f"error:{task.error_code or 'unknown'}",
                    ),
                )
            )
        return candidates

    def _failed_task_account_id(
        self,
        task: OperationalTask,
        *,
        sole_account_id: UUID | None,
    ) -> UUID | None:
        if task.task_type == "risk_scan":
            return self._session.scalar(
                select(RiskScan.account_id).where(
                    RiskScan.id == task.task_id,
                    RiskScan.workspace_id == self._context.workspace_id,
                )
            )
        return sole_account_id

    def _all_analysis_items(
        self,
        platform: Platform,
        account_id: UUID,
    ) -> list[AnalysisQueueItem]:
        first = self._workbench.analysis_queue(
            platform,
            account_id=account_id,
            status=None,
            page=1,
            page_size=100,
            sort="newest",
        )
        items: list[AnalysisQueueItem] = list(first.items)
        for page in range(2, first.pages + 1):
            items.extend(
                self._workbench.analysis_queue(
                    platform,
                    account_id=account_id,
                    status=None,
                    page=page,
                    page_size=100,
                    sort="newest",
                ).items
            )
        return items

    def _all_preflight_items(
        self,
        platform: Platform,
        account_id: UUID,
    ) -> list[PreflightQueueItem]:
        first = self._workbench.preflight_queue(
            platform,
            account_id=account_id,
            status=None,
            page=1,
            page_size=100,
            sort="newest",
        )
        items: list[PreflightQueueItem] = list(first.items)
        for page in range(2, first.pages + 1):
            items.extend(
                self._workbench.preflight_queue(
                    platform,
                    account_id=account_id,
                    status=None,
                    page=page,
                    page_size=100,
                    sort="newest",
                ).items
            )
        return items

    def _preflight_candidate(
        self,
        *,
        platform: Platform,
        account_id: UUID,
        item: PreflightQueueItem,
    ) -> BriefingCandidate | None:
        status = item.status
        content_id = item.content_id
        scan_id = item.scan_id
        evidence_status = item.evidence_status
        refs = [f"content:{content_id}"]
        if scan_id is not None:
            refs.append(f"risk_scan:{scan_id}")
        if status == "high_risk_blocked":
            return self._candidate(
                kind=CandidateKind.HIGH_RISK_BLOCKED,
                platform=platform,
                account_id=account_id,
                content_id=content_id,
                ranks=(5, 5, 5 if evidence_status == "available" else 3, 4, 4),
                evidence_refs=tuple(refs),
            )
        if status == "low_confidence_ocr":
            return self._candidate(
                kind=CandidateKind.LOW_CONFIDENCE_OCR,
                platform=platform,
                account_id=account_id,
                content_id=content_id,
                ranks=(4, 4, 3, 3, 3),
                evidence_refs=tuple(refs),
            )
        if status == "no_active_rag_evidence":
            return self._candidate(
                kind=CandidateKind.NO_ACTIVE_RAG_EVIDENCE,
                platform=platform,
                account_id=account_id,
                content_id=content_id,
                ranks=(4, 3, 2, 3, 3),
                evidence_refs=tuple(refs),
            )
        if status in {
            "pending_scan",
            "modified_awaiting_rescan",
            "review_required",
            "scan_failed",
        }:
            return self._candidate(
                kind=CandidateKind.PREFLIGHT_REVIEW_REQUIRED,
                platform=platform,
                account_id=account_id,
                content_id=content_id,
                ranks=(3, 3, 3, 3, 3),
                evidence_refs=tuple(refs),
            )
        return None

    def _analysis_candidate(
        self,
        *,
        platform: Platform,
        account_id: UUID,
        item: AnalysisQueueItem,
    ) -> BriefingCandidate | None:
        status = item.status
        content_id = item.content_id
        refs = (f"content:{content_id}",)
        if status == "configuration_required":
            return self._candidate(
                kind=CandidateKind.CONFIGURATION_REQUIRED,
                platform=platform,
                account_id=account_id,
                content_id=content_id,
                ranks=(4, 3, 4, 3, 2),
                evidence_refs=refs,
            )
        if status in {"pending", "failed", "insufficient_sample"}:
            return self._candidate(
                kind=CandidateKind.PENDING_ANALYSIS,
                platform=platform,
                account_id=account_id,
                content_id=content_id,
                ranks=(2, 1, 2, 2, 3),
                evidence_refs=refs,
            )
        return None

    def _candidate(
        self,
        *,
        kind: CandidateKind,
        platform: Platform,
        account_id: UUID,
        content_id: UUID | None,
        ranks: tuple[int, int, int, int, int],
        evidence_refs: tuple[str, ...],
    ) -> BriefingCandidate:
        title, reason = _COPY[kind]
        return BriefingCandidate(
            kind=kind,
            workspace_id=self._context.workspace_id,
            platform=platform,
            account_id=account_id,
            content_id=content_id,
            blocking_rank=ranks[0],
            severity_rank=ranks[1],
            evidence_rank=ranks[2],
            objective_rank=ranks[3],
            executable_rank=ranks[4],
            repeat_penalty=0,
            evidence_refs=evidence_refs,
            safe_title=title,
            safe_reason=reason,
        )

    def _input_state(
        self,
        *,
        excluded_analysis_ids: frozenset[UUID] = frozenset(),
        excluded_generation_ids: frozenset[UUID] = frozenset(),
        excluded_scan_ids: frozenset[UUID] = frozenset(),
        excluded_export_ids: frozenset[UUID] = frozenset(),
    ) -> tuple[
        dict[str, object],
        datetime,
        list[OperationalTask],
        list[ImportBatch],
    ]:
        workspace_id = self._context.workspace_id
        workspace = self._session.scalar(
            select(Workspace).where(Workspace.id == workspace_id)
        )
        if workspace is None:
            raise LookupError("workspace not found")
        accounts = list(
            self._session.scalars(
                select(PlatformAccount)
                .where(PlatformAccount.workspace_id == workspace_id)
                .order_by(PlatformAccount.id)
            )
        )
        contents = list(
            self._session.scalars(
                select(Content)
                .where(
                    Content.workspace_id == workspace_id,
                    Content.deleted_at.is_(None),
                )
                .order_by(Content.id)
            )
        )
        snapshots = list(
            self._session.scalars(
                select(DataSnapshot)
                .where(
                    DataSnapshot.workspace_id == workspace_id,
                    DataSnapshot.confirmed.is_(True),
                )
                .order_by(DataSnapshot.id)
            )
        )
        import_batches = list(
            self._session.scalars(
                select(ImportBatch)
                .where(ImportBatch.workspace_id == workspace_id)
                .order_by(ImportBatch.id)
            )
        )
        analysis_query = select(AnalysisRun).where(
            AnalysisRun.workspace_id == workspace_id
        )
        if excluded_analysis_ids:
            analysis_query = analysis_query.where(
                AnalysisRun.id.not_in(excluded_analysis_ids)
            )
        analyses = list(
            self._session.scalars(analysis_query.order_by(AnalysisRun.id))
        )
        scan_query = select(RiskScan).where(
            RiskScan.workspace_id == workspace_id
        )
        if excluded_scan_ids:
            scan_query = scan_query.where(
                RiskScan.id.not_in(excluded_scan_ids)
            )
        scans = list(
            self._session.scalars(scan_query.order_by(RiskScan.id))
        )
        objectives = list(
            self._session.scalars(
                select(ObjectiveProfile)
                .where(ObjectiveProfile.workspace_id == workspace_id)
                .order_by(ObjectiveProfile.id)
            )
        )
        benchmarks = list(
            self._session.scalars(
                select(BenchmarkProfile)
                .where(BenchmarkProfile.workspace_id == workspace_id)
                .order_by(BenchmarkProfile.id)
            )
        )
        columns = list(
            self._session.scalars(
                select(ColumnCampaign)
                .where(ColumnCampaign.workspace_id == workspace_id)
                .order_by(ColumnCampaign.id)
            )
        )
        model_configs = list(
            self._session.scalars(
                select(ModelConfig)
                .where(ModelConfig.workspace_id == workspace_id)
                .order_by(ModelConfig.id)
            )
        )
        tasks = SQLAlchemyOperationsStore(
            self._session,
            request_id="agent-briefing-read",
            actor_id=self._context.member_id,
        ).list(workspace_id)
        if (
            excluded_analysis_ids
            or excluded_generation_ids
            or excluded_scan_ids
            or excluded_export_ids
        ):
            excluded_task_ids = (
                excluded_analysis_ids
                | excluded_generation_ids
                | excluded_scan_ids
                | excluded_export_ids
            )
            event_conditions = []
            if excluded_analysis_ids:
                event_conditions.append(
                    ProductEvent.analysis_run_id.in_(
                        excluded_analysis_ids
                    )
                )
            if excluded_generation_ids:
                event_conditions.append(
                    ProductEvent.generation_run_id.in_(
                        excluded_generation_ids
                    )
                )
            excluded_outbox_ids = (
                set(
                    self._session.scalars(
                        select(ProductEventOutbox.id)
                        .join(
                            ProductEvent,
                            ProductEvent.id == ProductEventOutbox.event_id,
                        )
                        .where(or_(*event_conditions))
                    )
                )
                if event_conditions
                else set()
            )
            tasks = [
                task
                for task in tasks
                if (
                    task.task_id not in excluded_task_ids
                    and not (
                        task.task_type == "product_event_outbox"
                        and task.task_id in excluded_outbox_ids
                    )
                )
            ]
        cutoff_candidates = [workspace.updated_at]
        cutoff_candidates.extend(item.updated_at for item in accounts)
        cutoff_candidates.extend(item.updated_at for item in contents)
        cutoff_candidates.extend(item.updated_at for item in snapshots)
        cutoff_candidates.extend(item.updated_at for item in import_batches)
        cutoff_candidates.extend(item.updated_at for item in analyses)
        cutoff_candidates.extend(item.updated_at for item in scans)
        cutoff_candidates.extend(item.updated_at for item in objectives)
        cutoff_candidates.extend(item.updated_at for item in benchmarks)
        cutoff_candidates.extend(item.updated_at for item in columns)
        cutoff_candidates.extend(item.updated_at for item in model_configs)
        cutoff_candidates.extend(item.updated_at for item in tasks)
        cutoff = max(cutoff_candidates).astimezone(UTC)
        state: dict[str, object] = {
            "workspace": {
                "id": str(workspace.id),
                "updated_at": _iso(workspace.updated_at),
                "deletion_version": workspace.deletion_version,
            },
            "accounts": [
                {
                    "id": str(item.id),
                    "platform": item.platform.value,
                    "updated_at": _iso(item.updated_at),
                }
                for item in accounts
            ],
            "contents": [
                {
                    "id": str(item.id),
                    "account_id": str(item.account_id),
                    "platform": item.platform.value,
                    "status": item.status.value,
                    "column_campaign_id": (
                        str(item.column_campaign_id)
                        if item.column_campaign_id is not None
                        else None
                    ),
                    "updated_at": _iso(item.updated_at),
                }
                for item in contents
            ],
            "confirmed_snapshots": [
                {
                    "id": str(item.id),
                    "content_id": str(item.content_id),
                    "account_id": str(item.account_id),
                    "platform": item.platform.value,
                    "maturity_bucket": item.maturity_bucket,
                    "confirmed_at": (
                        _iso(item.confirmed_at)
                        if item.confirmed_at is not None
                        else None
                    ),
                    "updated_at": _iso(item.updated_at),
                }
                for item in snapshots
            ],
            "import_batches": [
                {
                    "id": str(item.id),
                    "account_id": str(item.account_id),
                    "platform": item.platform.value,
                    "status": item.status.value,
                    "source_kind": item.source_kind.value,
                    "updated_at": _iso(item.updated_at),
                }
                for item in import_batches
            ],
            "analyses": [
                {
                    "id": str(item.id),
                    "content_id": str(item.content_id),
                    "account_id": str(item.account_id),
                    "status": item.status.value,
                    "model_version": item.model_version,
                    "prompt_version": item.prompt_version,
                    "algorithm_version": item.algorithm_version,
                    "model_config_version": item.model_config_version,
                    "updated_at": _iso(item.updated_at),
                }
                for item in analyses
            ],
            "risk_scans": [
                {
                    "id": str(item.id),
                    "content_id": str(item.content_id),
                    "account_id": str(item.account_id),
                    "platform": item.platform.value,
                    "status": item.status.value,
                    "input_fingerprint": item.input_fingerprint,
                    "rule_version": item.rule_version,
                    "evidence_version": item.evidence_version,
                    "scanner_version": item.scanner_version,
                    "updated_at": _iso(item.updated_at),
                }
                for item in scans
            ],
            "configuration": {
                "objectives": [
                    {
                        "id": str(item.id),
                        "account_id": str(item.account_id),
                        "version": item.version,
                        "updated_at": _iso(item.updated_at),
                    }
                    for item in objectives
                ],
                "benchmarks": [
                    {
                        "id": str(item.id),
                        "account_id": str(item.account_id),
                        "version": item.version,
                        "updated_at": _iso(item.updated_at),
                    }
                    for item in benchmarks
                ],
                "columns": [
                    {
                        "id": str(item.id),
                        "account_id": str(item.account_id),
                        "objective_profile_id": (
                            str(item.objective_profile_id)
                            if item.objective_profile_id is not None
                            else None
                        ),
                        "benchmark_profile_id": (
                            str(item.benchmark_profile_id)
                            if item.benchmark_profile_id is not None
                            else None
                        ),
                        "starts_at": (
                            _iso(item.starts_at)
                            if item.starts_at is not None
                            else None
                        ),
                        "ends_at": (
                            _iso(item.ends_at)
                            if item.ends_at is not None
                            else None
                        ),
                        "updated_at": _iso(item.updated_at),
                    }
                    for item in columns
                ],
                "model_configs": [
                    {
                        "id": str(item.id),
                        "provider": item.provider,
                        "model_id": item.model_id,
                        "capabilities": sorted(item.capabilities),
                        "status": item.status.value,
                        "configuration_revision": item.configuration_revision,
                        "updated_at": _iso(item.updated_at),
                    }
                    for item in model_configs
                ],
            },
            "tasks": [
                {
                    "id": str(item.task_id),
                    "task_type": item.task_type,
                    "status": item.status,
                    "error_code": item.error_code,
                    "fencing_token": item.fencing_token,
                    "updated_at": _iso(item.updated_at),
                }
                for item in tasks
            ],
        }
        return state, cutoff, tasks, import_batches

    @staticmethod
    def _fingerprint(payload: dict[str, object]) -> str:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _read(record: AgentBriefing) -> DailyBriefingRead:
        candidates = tuple(
            BriefingCandidateRead.model_validate(item)
            for item in record.candidates
        )
        primary = (
            BriefingCandidateRead.model_validate(
                record.priority_candidate
            )
            if record.priority_candidate is not None
            else None
        )
        return DailyBriefingRead(
            id=record.id,
            workspace_id=record.workspace_id,
            input_fingerprint=record.input_fingerprint,
            algorithm_version=record.algorithm_version,
            tool_catalog_version=record.tool_catalog_version,
            data_cutoff_at=record.data_cutoff_at,
            primary=primary,
            candidates=candidates,
            created_at=record.created_at,
        )


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


_COPY: dict[CandidateKind, tuple[str, str]] = {
    CandidateKind.HIGH_RISK_BLOCKED: (
        "先处理被高风险规则拦住的内容",
        "这项问题会直接阻止当前内容进入后续人工发布流程。",
    ),
    CandidateKind.LOW_CONFIDENCE_OCR: (
        "人工核对封面文字",
        "封面识别可信度不足，需要运营人员确认后再继续。",
    ),
    CandidateKind.NO_ACTIVE_RAG_EVIDENCE: (
        "补充或复核平台规则依据",
        "当前判断缺少有效规则证据，不能当作已经通过检查。",
    ),
    CandidateKind.PREFLIGHT_REVIEW_REQUIRED: (
        "完成发布前检查",
        "内容仍有未完成的检查或复检步骤。",
    ),
    CandidateKind.CONFIGURATION_REQUIRED: (
        "补齐分析所需配置",
        "现有配置不足，相关分析暂时无法继续。",
    ),
    CandidateKind.PERMISSION_SECURITY_FAILURE: (
        "处理权限或安全失败",
        "后台流程因权限或安全校验失败，必须人工处理且不能永久隐藏。",
    ),
    CandidateKind.FAILED_TASK: (
        "处理失败的后台任务",
        "后台流程没有完成，需要查看安全错误码后再决定是否重试。",
    ),
    CandidateKind.IMPORT_WAITING_CONFIRMATION: (
        "确认等待中的导入",
        "暂存数据还没有经过人工确认，尚未进入正式内容数据。",
    ),
    CandidateKind.PENDING_ANALYSIS: (
        "分析一条尚未完成诊断的内容",
        "当前内容还没有可用的最新分析结果。",
    ),
    CandidateKind.INCOMPLETE_DATA: (
        "先补齐账号数据",
        "账号数据或资料不完整，补齐后才能获得更可靠的建议。",
    ),
}
