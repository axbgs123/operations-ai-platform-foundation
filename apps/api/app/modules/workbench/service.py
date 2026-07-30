from datetime import UTC, datetime, timedelta
from typing import Literal, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, exists, func, select
from sqlalchemy.orm import Session, aliased

from app.core.observability import SQLAlchemyOperationsStore
from app.core.security import WorkspaceContext
from app.modules.analysis.models import (
    AnalysisRun,
    AnalysisRunStatus,
    AnalysisSuggestion,
)
from app.modules.analytics.north_star import AnalyticsService
from app.modules.content.account_models import (
    ColumnCampaign,
    Platform,
    PlatformAccount,
)
from app.modules.content.models import Content
from app.modules.imports.models import ImportBatch, ImportBatchStatus
from app.modules.metrics.models import DataSnapshot
from app.modules.metrics.maturity import calculate_completeness
from app.modules.risk_rag.models import RiskScan, RiskScanStatus
from app.modules.workbench.schemas import (
    AnalysisQueueItem,
    AnalysisQueueRead,
    AnalysisQueueSort,
    AnalysisQueueStatus,
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
        status: AnalysisQueueStatus | None,
        page: int,
        page_size: int,
        sort: AnalysisQueueSort,
    ) -> AnalysisQueueRead:
        if account_id is not None:
            self._account(account_id, platform)
        latest_rank = (
            select(
                AnalysisRun.id.label("run_id"),
                AnalysisRun.content_id.label("content_id"),
                func.row_number().over(
                    partition_by=AnalysisRun.content_id,
                    order_by=(
                        AnalysisRun.created_at.desc(),
                        AnalysisRun.id.desc(),
                    ),
                ).label("row_number"),
            )
            .where(
                AnalysisRun.workspace_id == self._context.workspace_id
            )
            .subquery()
        )
        latest_run = aliased(AnalysisRun)
        pending_suggestion = exists(
            select(AnalysisSuggestion.id).where(
                AnalysisSuggestion.workspace_id
                == self._context.workspace_id,
                AnalysisSuggestion.analysis_run_id == latest_run.id,
                AnalysisSuggestion.adoption_status == "saved",
            )
        )
        sample_count = func.coalesce(
            latest_run.evidence_bundle["benchmark"][
                "sample_count"
            ].as_integer(),
            0,
        )
        queue_status = case(
            (latest_run.id.is_(None), "pending"),
            (
                latest_run.status.in_(
                    [AnalysisRunStatus.PENDING, AnalysisRunStatus.RUNNING]
                ),
                "running",
            ),
            (
                latest_run.status == AnalysisRunStatus.FAILED,
                case(
                    (
                        latest_run.error_code
                        == "MODEL_CONFIGURATION_REQUIRED",
                        "configuration_required",
                    ),
                    else_="failed",
                ),
            ),
            (
                (latest_run.status == AnalysisRunStatus.SUCCEEDED)
                & pending_suggestion,
                "suggestion_pending",
            ),
            (
                (latest_run.status == AnalysisRunStatus.SUCCEEDED)
                & (sample_count < 5),
                "insufficient_sample",
            ),
            else_="completed",
        )
        latest_maturity = (
            select(DataSnapshot.maturity_bucket)
            .where(
                DataSnapshot.workspace_id == self._context.workspace_id,
                DataSnapshot.content_id == Content.id,
                DataSnapshot.confirmed.is_(True),
            )
            .order_by(
                DataSnapshot.collected_at.desc(),
                DataSnapshot.id.desc(),
            )
            .limit(1)
            .scalar_subquery()
        )
        statement = (
            select(
                Content,
                PlatformAccount.name.label("account_name"),
                ColumnCampaign.name.label("column_name"),
                latest_run,
                latest_maturity.label("latest_maturity"),
                queue_status.label("queue_status"),
            )
            .join(
                PlatformAccount,
                PlatformAccount.id == Content.account_id,
            )
            .outerjoin(
                ColumnCampaign,
                and_(
                    ColumnCampaign.id == Content.column_campaign_id,
                    ColumnCampaign.workspace_id
                    == self._context.workspace_id,
                ),
            )
            .outerjoin(
                latest_rank,
                (latest_rank.c.content_id == Content.id)
                & (latest_rank.c.row_number == 1),
            )
            .outerjoin(latest_run, latest_run.id == latest_rank.c.run_id)
            .where(
                Content.workspace_id == self._context.workspace_id,
                Content.deleted_at.is_(None),
                Content.platform == platform,
                PlatformAccount.workspace_id == self._context.workspace_id,
            )
        )
        if account_id is not None:
            statement = statement.where(Content.account_id == account_id)
        if status is not None:
            statement = statement.where(queue_status == status)
        total_statement = statement.with_only_columns(
            Content.id,
            maintain_column_froms=True,
        ).order_by(None)
        total = int(
            self._session.scalar(
                select(func.count()).select_from(total_statement.subquery())
            )
            or 0
        )
        order = (
            (Content.created_at.asc(), Content.id.asc())
            if sort == "oldest"
            else (Content.created_at.desc(), Content.id.desc())
        )
        rows = self._session.execute(
            statement.order_by(*order)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        run_ids = {
            run.id for *_, run, _maturity, _status in rows if run is not None
        }
        suggestion_statuses = {
            suggestion.analysis_run_id: suggestion.adoption_status
            for suggestion in self._session.scalars(
                select(AnalysisSuggestion)
                .where(
                    AnalysisSuggestion.workspace_id
                    == self._context.workspace_id,
                    AnalysisSuggestion.analysis_run_id.in_(run_ids),
                )
                .order_by(
                    AnalysisSuggestion.created_at.desc(),
                    AnalysisSuggestion.id.desc(),
                )
            )
        } if run_ids else {}

        items: list[AnalysisQueueItem] = []
        for (
            content,
            account_name,
            column_name,
            run,
            maturity,
            item_status,
        ) in rows:
            report = run.report if run is not None and isinstance(run.report, dict) else {}
            bundle = (
                run.evidence_bundle
                if run is not None and isinstance(run.evidence_bundle, dict)
                else {}
            )
            benchmark = bundle.get("benchmark")
            actual_sample_count = (
                int(benchmark.get("sample_count", 0))
                if isinstance(benchmark, dict)
                else 0
            )
            confidence_value = report.get("confidence")
            confidence = (
                confidence_value
                if confidence_value in {"low", "medium", "high"}
                else "unknown"
            )
            typed_confidence = cast(
                Literal["low", "medium", "high", "unknown"],
                confidence,
            )
            summary = {
                "pending": "尚未开始分析",
                "running": "分析任务正在处理",
                "failed": "分析任务失败，可按安全错误码重试",
                "configuration_required": "分析所需模型尚未配置",
                "insufficient_sample": "可比较样本不足，结论已降级",
                "suggestion_pending": "分析完成，有建议等待采用或拒绝",
                "completed": "分析已完成",
            }[item_status]
            data_performance = report.get("data_performance")
            if isinstance(data_performance, dict):
                candidate_summary = data_performance.get("summary")
                if isinstance(candidate_summary, str) and candidate_summary.strip():
                    summary = candidate_summary.strip()[:200]
            evidence = report.get("evidence")
            if item_status == "insufficient_sample":
                evidence_status = "insufficient_sample"
            elif isinstance(evidence, list) and evidence:
                evidence_status = "available"
            else:
                evidence_status = "missing"
            suggestion_status = (
                suggestion_statuses.get(run.id, "none")
                if run is not None
                else "none"
            )
            items.append(
                AnalysisQueueItem(
                    content_id=content.id,
                    account_id=content.account_id,
                    account_name=account_name,
                    column_campaign_id=content.column_campaign_id,
                    column_campaign_name=column_name,
                    platform=content.platform.value,
                    content_type=content.content_type.value,
                    status=item_status,
                    maturity=maturity,
                    sample_count=min(actual_sample_count, 10_000),
                    analysis_version=(
                        run.algorithm_version if run is not None else None
                    ),
                    safe_summary=summary,
                    confidence=typed_confidence,
                    evidence_status=cast(
                        Literal[
                            "available",
                            "missing",
                            "insufficient_sample",
                        ],
                        evidence_status,
                    ),
                    suggestion_status=cast(
                        Literal["none", "saved", "adopted", "rejected"],
                        suggestion_status,
                    ),
                )
            )
        return AnalysisQueueRead(
            platform=platform.value,
            account_id=account_id,
            status=status,
            sort=sort,
            page=page,
            page_size=page_size,
            total=total,
            pages=(total + page_size - 1) // page_size,
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
