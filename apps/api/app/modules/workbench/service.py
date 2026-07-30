from datetime import UTC, datetime, timedelta
from typing import Literal, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.observability import SQLAlchemyOperationsStore
from app.core.security import WorkspaceContext
from app.modules.analysis.models import AnalysisRun, AnalysisRunStatus
from app.modules.analytics.north_star import AnalyticsService
from app.modules.content.account_models import Platform, PlatformAccount
from app.modules.content.models import Content
from app.modules.imports.models import ImportBatch, ImportBatchStatus
from app.modules.metrics.models import DataSnapshot
from app.modules.metrics.maturity import calculate_completeness
from app.modules.risk_rag.models import RiskScan, RiskScanStatus
from app.modules.workbench.schemas import (
    AnalysisQueueItem,
    AnalysisQueueRead,
    PreflightQueueItem,
    PreflightQueueRead,
    WorkbenchAccountCard,
    WorkbenchAccountOption,
    WorkbenchAttentionCounts,
    WorkbenchCompleteness,
    WorkbenchContentTypeCounts,
    WorkbenchContextRead,
    WorkbenchDataStatus,
    WorkbenchNextAction,
    WorkbenchOverviewRead,
)
from app.modules.workspace.models import Workspace, WorkspaceMember


class WorkbenchService:
    def __init__(self, session: Session, context: WorkspaceContext) -> None:
        self._session = session
        self._context = context

    def _accounts(
        self,
        platform: Platform | None = None,
        account_id: UUID | None = None,
    ) -> list[PlatformAccount]:
        query = select(PlatformAccount).where(
            PlatformAccount.workspace_id == self._context.workspace_id
        )
        if platform is not None:
            query = query.where(PlatformAccount.platform == platform)
        if account_id is not None:
            query = query.where(PlatformAccount.id == account_id)
        return list(
            self._session.scalars(
                query.order_by(
                    PlatformAccount.platform,
                    PlatformAccount.name,
                    PlatformAccount.id,
                )
            )
        )

    def _account(
        self,
        account_id: UUID,
        platform: Platform,
    ) -> PlatformAccount:
        account = self._session.scalar(
            select(PlatformAccount).where(
                PlatformAccount.id == account_id,
                PlatformAccount.workspace_id == self._context.workspace_id,
                PlatformAccount.platform == platform,
            )
        )
        if account is None:
            raise LookupError("account not found")
        return account

    def _failed_task_count(self) -> int:
        tasks = SQLAlchemyOperationsStore(
            self._session,
            request_id="workbench-read",
            actor_id=self._context.member_id,
        ).list(self._context.workspace_id)
        return sum(
            task.status in {"failed", "dead_letter", "compensation_required"}
            for task in tasks
        )

    def context(self) -> WorkbenchContextRead:
        if self._context.member_id is None or self._context.role == "demo":
            raise PermissionError("private workbench unavailable")
        workspace = self._session.scalar(
            select(Workspace).where(
                Workspace.id == self._context.workspace_id,
                Workspace.status == "active",
            )
        )
        member = self._session.scalar(
            select(WorkspaceMember).where(
                WorkspaceMember.id == self._context.member_id,
                WorkspaceMember.workspace_id == self._context.workspace_id,
                WorkspaceMember.revoked_at.is_(None),
            )
        )
        if workspace is None or member is None:
            raise LookupError("workspace not found")
        return WorkbenchContextRead(
            workspace_id=workspace.id,
            workspace_name=workspace.name,
            member_id=member.id,
            member_display_name=member.display_name,
            role=self._context.role,
            accounts=[
                WorkbenchAccountOption(
                    account_id=account.id,
                    platform=account.platform.value,
                    name=account.name,
                )
                for account in self._accounts()
            ],
            failed_task_count=self._failed_task_count(),
        )

    def _contents(
        self,
        platform: Platform | None = None,
        account_id: UUID | None = None,
    ) -> list[Content]:
        query = select(Content).where(
            Content.workspace_id == self._context.workspace_id,
            Content.deleted_at.is_(None),
        )
        if platform is not None:
            query = query.where(Content.platform == platform)
        if account_id is not None:
            query = query.where(Content.account_id == account_id)
        return list(
            self._session.scalars(query.order_by(Content.created_at, Content.id))
        )

    def _latest_analysis_runs(
        self,
        content_ids: list[UUID],
    ) -> dict[UUID, AnalysisRun]:
        if not content_ids:
            return {}
        runs = self._session.scalars(
            select(AnalysisRun)
            .where(
                AnalysisRun.workspace_id == self._context.workspace_id,
                AnalysisRun.content_id.in_(content_ids),
            )
            .order_by(
                AnalysisRun.created_at.desc(),
                AnalysisRun.id.desc(),
            )
        )
        latest: dict[UUID, AnalysisRun] = {}
        for run in runs:
            latest.setdefault(run.content_id, run)
        return latest

    def _latest_risk_scans(
        self,
        content_ids: list[UUID],
    ) -> dict[UUID, RiskScan]:
        if not content_ids:
            return {}
        scans = self._session.scalars(
            select(RiskScan)
            .where(
                RiskScan.workspace_id == self._context.workspace_id,
                RiskScan.content_id.in_(content_ids),
            )
            .order_by(
                RiskScan.created_at.desc(),
                RiskScan.id.desc(),
            )
        )
        latest: dict[UUID, RiskScan] = {}
        for scan in scans:
            latest.setdefault(scan.content_id, scan)
        return latest

    @staticmethod
    def _findings(scan: RiskScan | None) -> list[dict[str, object]]:
        if scan is None or not isinstance(scan.result, dict):
            return []
        findings = scan.result.get("findings")
        if not isinstance(findings, list):
            return []
        return [finding for finding in findings if isinstance(finding, dict)]

    def analysis_queue(
        self,
        platform: Platform,
        *,
        account_id: UUID | None,
    ) -> AnalysisQueueRead:
        if account_id is not None:
            self._account(account_id, platform)
        contents = self._contents(platform, account_id)
        latest = self._latest_analysis_runs([content.id for content in contents])
        items: list[AnalysisQueueItem] = []
        for content in contents:
            run = latest.get(content.id)
            if run is not None and run.status == AnalysisRunStatus.SUCCEEDED:
                continue
            status: Literal[
                "not_analyzed",
                "queued",
                "running",
                "failed",
            ]
            if run is None:
                status = "not_analyzed"
            elif run.status == AnalysisRunStatus.PENDING:
                status = "queued"
            elif run.status == AnalysisRunStatus.RUNNING:
                status = "running"
            elif run.status == AnalysisRunStatus.FAILED:
                status = "failed"
            else:
                status = "not_analyzed"
            summary = {
                "not_analyzed": "尚未开始分析",
                "queued": "分析任务正在排队",
                "running": "分析任务正在运行",
                "failed": "分析任务失败，可检查配置后重试",
            }[status]
            items.append(
                AnalysisQueueItem(
                    content_id=content.id,
                    account_id=content.account_id,
                    platform=content.platform.value,
                    content_type=content.content_type.value,
                    status=status,
                    snapshot_count=min(
                        len(run.snapshot_ids) if run is not None else 0,
                        10_000,
                    ),
                    analysis_version=(
                        run.algorithm_version if run is not None else None
                    ),
                    safe_summary=summary,
                )
            )
        return AnalysisQueueRead(
            platform=platform.value,
            account_id=account_id,
            total=len(items),
            items=items,
        )

    def preflight_queue(
        self,
        platform: Platform,
        *,
        account_id: UUID | None,
    ) -> PreflightQueueRead:
        if account_id is not None:
            self._account(account_id, platform)
        contents = self._contents(platform, account_id)
        latest = self._latest_risk_scans([content.id for content in contents])
        items: list[PreflightQueueItem] = []
        for content in contents:
            scan = latest.get(content.id)
            findings = self._findings(scan)
            severities = {
                finding.get("severity")
                for finding in findings
                if isinstance(finding.get("severity"), str)
            }
            requires_review = any(
                finding.get("requires_human_review") is True for finding in findings
            )
            status: Literal[
                "not_scanned",
                "scan_pending",
                "high_risk",
                "review_required",
                "clear",
                "scan_failed",
            ]
            if scan is None:
                status = "not_scanned"
                summary = "尚未执行发布前检查"
            elif scan.status in {
                RiskScanStatus.QUEUED,
                RiskScanStatus.RUNNING,
                RiskScanStatus.RETRYING,
            }:
                status = "scan_pending"
                summary = "发布前检查正在处理"
            elif scan.status in {
                RiskScanStatus.FAILED,
                RiskScanStatus.CANCELLED,
            }:
                status = "scan_failed"
                summary = "发布前检查未完成"
            elif "high" in severities:
                status = "high_risk"
                summary = f"检测到 {len(findings)} 项风险，其中包含高风险"
            elif requires_review:
                status = "review_required"
                summary = f"检测到 {len(findings)} 项需要人工复核的问题"
            else:
                status = "clear"
                summary = "当前扫描未发现高风险问题"
            items.append(
                PreflightQueueItem(
                    content_id=content.id,
                    account_id=content.account_id,
                    platform=content.platform.value,
                    content_type=content.content_type.value,
                    status=status,
                    scan_id=scan.id if scan is not None else None,
                    finding_count=min(len(findings), 10_000),
                    scan_version=(scan.scanner_version if scan is not None else None),
                    safe_summary=summary,
                )
            )
        return PreflightQueueRead(
            platform=platform.value,
            account_id=account_id,
            total=len(items),
            items=items,
        )

    def overview(
        self,
        platform: Platform | None = None,
        *,
        account_id: UUID | None = None,
    ) -> WorkbenchOverviewRead:
        if account_id is not None:
            if platform is None:
                raise LookupError("platform required for account scope")
            self._account(account_id, platform)
        accounts = self._accounts(platform, account_id)
        all_contents = self._contents(platform, account_id)
        content_ids = [content.id for content in all_contents]
        latest_analysis = self._latest_analysis_runs(content_ids)
        latest_scans = self._latest_risk_scans(content_ids)
        pending_by_account: dict[UUID, int] = {account.id: 0 for account in accounts}
        risk_by_account: dict[UUID, int] = {account.id: 0 for account in accounts}
        content_type_counts: dict[UUID, dict[str, int]] = {
            account.id: {"video": 0, "image_text": 0} for account in accounts
        }
        high_risk_count = 0
        low_confidence_count = 0
        for content in all_contents:
            content_type_counts[content.account_id][content.content_type.value] += 1
            run = latest_analysis.get(content.id)
            if run is None or run.status != AnalysisRunStatus.SUCCEEDED:
                pending_by_account[content.account_id] += 1
            scan = latest_scans.get(content.id)
            findings = self._findings(scan)
            if any(finding.get("severity") == "high" for finding in findings):
                risk_by_account[content.account_id] += 1
                high_risk_count += 1
            if any(
                finding.get("requires_human_review") is True
                and isinstance(finding.get("ocr_confidence"), (int, float))
                for finding in findings
            ):
                low_confidence_count += 1

        snapshot_count_by_account: dict[UUID, int] = {
            account.id: 0 for account in accounts
        }
        latest_maturity_by_account: dict[
            UUID,
            Literal["1h", "24h", "72h", "7d"],
        ] = {}
        snapshot_ages_by_account: dict[UUID, list[timedelta]] = {
            account.id: [] for account in accounts
        }
        selected_account_ids = [account.id for account in accounts]
        confirmed_snapshots: list[DataSnapshot] = (
            list(
                self._session.scalars(
                    select(DataSnapshot)
                    .where(
                        DataSnapshot.workspace_id == self._context.workspace_id,
                        DataSnapshot.account_id.in_(selected_account_ids),
                        DataSnapshot.confirmed.is_(True),
                    )
                    .order_by(
                        DataSnapshot.collected_at.desc(),
                        DataSnapshot.id.desc(),
                    )
                )
            )
            if selected_account_ids
            else []
        )
        for snapshot in confirmed_snapshots:
            snapshot_count_by_account[snapshot.account_id] += 1
            snapshot_ages_by_account[snapshot.account_id].append(
                timedelta(seconds=snapshot.age_seconds)
            )
            latest_maturity_by_account.setdefault(
                snapshot.account_id,
                cast(
                    Literal["1h", "24h", "72h", "7d"],
                    snapshot.maturity_bucket,
                ),
            )
        imports_query = select(func.count(ImportBatch.id)).where(
            ImportBatch.workspace_id == self._context.workspace_id,
            ImportBatch.status == ImportBatchStatus.PREVIEW,
        )
        if platform is not None:
            imports_query = imports_query.where(ImportBatch.platform == platform)
        if account_id is not None:
            imports_query = imports_query.where(ImportBatch.account_id == account_id)
        imports_waiting = int(self._session.scalar(imports_query) or 0)
        failed_task_count = self._failed_task_count()
        analytics = AnalyticsService(self._session, self._context)
        loops = analytics.effective_loops()
        local_now = datetime.now(UTC).astimezone(ZoneInfo("Asia/Shanghai"))
        year, week, _ = local_now.isocalendar()
        current_week = f"{year}-W{week:02d}"
        loop_content_ids: list[UUID] = []
        for loop in loops:
            content_id = loop.evidence_ids.get("content_id")
            if loop.iso_week != current_week or content_id is None:
                continue
            try:
                loop_content_ids.append(UUID(content_id))
            except ValueError:
                continue
        closed_loop_account_ids = (
            set(
                self._session.scalars(
                    select(Content.account_id).where(
                        Content.workspace_id == self._context.workspace_id,
                        Content.id.in_(loop_content_ids),
                    )
                )
            )
            if loop_content_ids
            else set()
        )
        cards: list[WorkbenchAccountCard] = []
        for account in accounts:
            completeness = analytics.completeness(account.id)
            cards.append(
                WorkbenchAccountCard(
                    account_id=account.id,
                    platform=account.platform.value,
                    name=account.name,
                    content_type_counts=WorkbenchContentTypeCounts(
                        **content_type_counts[account.id]
                    ),
                    completeness=WorkbenchCompleteness(
                        score=completeness.score,
                        missing_items=list(completeness.missing_items),
                        version=completeness.completeness_version,
                    ),
                    pending_analysis_count=pending_by_account[account.id],
                    open_risk_count=risk_by_account[account.id],
                    has_current_week_closed_loop=(
                        account.id in closed_loop_account_ids
                    ),
                    confirmed_snapshot_count=snapshot_count_by_account[account.id],
                    latest_maturity_bucket=latest_maturity_by_account.get(
                        account.id
                    ),
                )
            )

        pending_total = sum(pending_by_account.values())
        next_action = None
        workspace_prefix = f"/workspaces/{self._context.workspace_id}"
        if imports_waiting:
            next_action = WorkbenchNextAction(
                kind="confirm_import",
                label="确认等待中的数据导入",
                href=f"{workspace_prefix}/imports",
            )
        elif high_risk_count:
            next_action = WorkbenchNextAction(
                kind="review_preflight",
                label="复核高风险内容",
                href=f"{workspace_prefix}/preflight",
            )
        elif pending_total:
            next_action = WorkbenchNextAction(
                kind="review_analysis",
                label="处理待分析内容",
                href=f"{workspace_prefix}/analysis",
            )
        return WorkbenchOverviewRead(
            data_status=WorkbenchDataStatus(
                account_count=len(accounts),
                accounts_missing_recommended_snapshot=sum(
                    bool(calculate_completeness(ages).missing)
                    for ages in snapshot_ages_by_account.values()
                ),
                imports_waiting_confirmation=imports_waiting,
            ),
            attention=WorkbenchAttentionCounts(
                pending_analysis_count=pending_total,
                high_risk_count=high_risk_count,
                low_confidence_ocr_count=low_confidence_count,
                failed_task_count=failed_task_count,
            ),
            next_action=next_action,
            accounts=cards,
        )
