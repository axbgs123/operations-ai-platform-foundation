from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.storage import InvalidUploadToken, Storage, get_storage
from app.modules.content.account_models import ColumnCampaign, Platform, PlatformAccount
from app.modules.content.models import (
    AssetCategory,
    Content,
    ContentAsset,
    ContentStatus,
)
from app.modules.content.schemas import (
    AssetConfirmRequest,
    AssetPresignRequest,
    AssetRead,
    AssetUploadGrantRead,
    ContentCreate,
    ContentDetailRead,
    ContentListPageRead,
    ContentRead,
    ContentUpdate,
)
from app.modules.content.service import ContentService
from app.modules.analysis.models import AnalysisRun
from app.modules.generation.models import CoverGenerationRun
from app.modules.metrics.models import (
    ContentType,
    DataSnapshot,
    SnapshotMetricValue,
)
from app.modules.metrics.dashboard import DashboardService
from app.modules.metrics.maturity import MaturityBucket
from app.modules.metrics.snapshot_service import SnapshotService
from app.modules.risk_rag.models import RiskScan
from app.modules.workspace.auth import InviteAuthService
from app.modules.workspace.permissions import PermissionDenied


router = APIRouter(prefix="/v1/contents", tags=["contents"])
workspace_content_router = APIRouter(
    prefix="/v1/workspaces/{workspace_id}/contents",
    tags=["contents"],
)
DatabaseSession = Annotated[Session, Depends(get_session)]
ObjectStorage = Annotated[Storage, Depends(get_storage)]


def _service(
    session: Session,
    session_token: str | None,
    csrf_token: str | None,
    *,
    mutation: bool,
    workspace_id: UUID | None = None,
) -> ContentService:
    if session_token is None:
        raise HTTPException(status_code=401, detail="invalid session")
    auth = InviteAuthService(session)
    context = auth.authenticate(session_token)
    if context is None:
        raise HTTPException(status_code=401, detail="invalid session")
    if workspace_id is not None and context.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="workspace not found")
    if mutation and (
        csrf_token is None or not auth.validate_csrf(session_token, csrf_token)
    ):
        raise HTTPException(status_code=403, detail="CSRF validation failed")
    return ContentService(session, context)


def _asset_payload(asset: ContentAsset, storage: Storage | None = None) -> dict:
    download_url = None
    download_expires_at = None
    if storage is not None:
        download_url, download_expires_at = storage.presign_download(asset.object_key)
    return {
        "id": asset.id,
        "category": asset.category.value,
        "file_name": asset.file_name,
        "mime_type": asset.mime_type,
        "size": asset.size,
        "download_url": download_url,
        "download_url_expires_at": download_expires_at,
    }


def _payload(session: Session, content: Content, storage: Storage | None = None) -> dict:
    account = session.get(PlatformAccount, content.account_id)
    column_campaign = (
        session.get(ColumnCampaign, content.column_campaign_id)
        if content.column_campaign_id
        else None
    )
    assets = list(
        session.scalars(
            select(ContentAsset).where(ContentAsset.content_id == content.id)
        )
    )
    return {
        "id": content.id,
        "workspace_id": content.workspace_id,
        "account_id": content.account_id,
        "account_name": account.name if account else "",
        "platform": content.platform.value,
        "content_type": content.content_type.value,
        "title": content.title,
        "body": content.body,
        "status": content.status.value,
        "column_campaign_id": content.column_campaign_id,
        "column_campaign_name": column_campaign.name if column_campaign else None,
        "work_url": content.work_url,
        "platform_content_id": content.platform_content_id,
        "published_title": content.published_title,
        "published_body": content.published_body,
        "published_at": content.published_at,
        "deleted_at": content.deleted_at,
        "objective_profile_id": content.objective_profile_id,
        "benchmark_profile_id": content.benchmark_profile_id,
        "assets": [_asset_payload(asset, storage) for asset in assets],
    }


def _risk_status(scan: RiskScan | None) -> str:
    if scan is None:
        return "not_scanned"
    if scan.status.value in {"queued", "running", "retrying"}:
        return "pending"
    if scan.status.value in {"failed", "cancelled"}:
        return "failed"
    raw_findings = (scan.result or {}).get("findings", [])
    findings = raw_findings if isinstance(raw_findings, list) else []
    severities = {
        str(finding.get("severity"))
        for finding in findings
        if isinstance(finding, dict)
    }
    for severity in ("high", "medium", "low"):
        if severity in severities:
            return severity
    return "clear"


def _list_items_payload(
    session: Session,
    service: ContentService,
    contents: list[Content],
    storage: Storage,
) -> list[dict]:
    if not contents:
        return []
    content_ids = [content.id for content in contents]
    account_ids = {content.account_id for content in contents}
    column_ids = {
        content.column_campaign_id
        for content in contents
        if content.column_campaign_id is not None
    }
    accounts = {
        account.id: account
        for account in session.scalars(
            select(PlatformAccount).where(
                PlatformAccount.workspace_id == service.context.workspace_id,
                PlatformAccount.id.in_(account_ids),
            )
        )
    }
    columns = {
        column.id: column
        for column in session.scalars(
            select(ColumnCampaign).where(
                ColumnCampaign.workspace_id == service.context.workspace_id,
                ColumnCampaign.id.in_(column_ids),
            )
        )
    } if column_ids else {}
    latest_snapshot_rank = (
        select(
            DataSnapshot.id.label("id"),
            func.row_number().over(
                partition_by=DataSnapshot.content_id,
                order_by=(
                    DataSnapshot.collected_at.desc(),
                    DataSnapshot.id.desc(),
                ),
            ).label("row_number"),
        )
        .where(
            DataSnapshot.workspace_id == service.context.workspace_id,
            DataSnapshot.content_id.in_(content_ids),
            DataSnapshot.confirmed.is_(True),
        )
        .subquery()
    )
    snapshots = list(
        session.scalars(
            select(DataSnapshot)
            .join(
                latest_snapshot_rank,
                DataSnapshot.id == latest_snapshot_rank.c.id,
            )
            .where(latest_snapshot_rank.c.row_number == 1)
        )
    )
    latest_snapshots = {
        snapshot.content_id: snapshot for snapshot in snapshots
    }
    maturity_rows = session.execute(
        select(
            DataSnapshot.content_id,
            DataSnapshot.maturity_bucket,
        )
        .where(
            DataSnapshot.workspace_id == service.context.workspace_id,
            DataSnapshot.content_id.in_(content_ids),
        )
        .distinct()
    )
    maturity_by_content: dict[UUID, set[str]] = {
        content_id: set() for content_id in content_ids
    }
    for content_id, maturity_bucket in maturity_rows:
        maturity_by_content[content_id].add(maturity_bucket)
    latest_analysis_rank = (
        select(
            AnalysisRun.id.label("id"),
            func.row_number().over(
                partition_by=AnalysisRun.content_id,
                order_by=(
                    AnalysisRun.created_at.desc(),
                    AnalysisRun.id.desc(),
                ),
            ).label("row_number"),
        )
        .where(
            AnalysisRun.workspace_id == service.context.workspace_id,
            AnalysisRun.content_id.in_(content_ids),
        )
        .subquery()
    )
    analyses = list(
        session.scalars(
            select(AnalysisRun)
            .join(
                latest_analysis_rank,
                AnalysisRun.id == latest_analysis_rank.c.id,
            )
            .where(latest_analysis_rank.c.row_number == 1)
        )
    )
    latest_analyses = {run.content_id: run for run in analyses}
    latest_scan_rank = (
        select(
            RiskScan.id.label("id"),
            func.row_number().over(
                partition_by=RiskScan.content_id,
                order_by=(
                    RiskScan.created_at.desc(),
                    RiskScan.id.desc(),
                ),
            ).label("row_number"),
        )
        .join(Content, Content.id == RiskScan.content_id)
        .where(
            RiskScan.workspace_id == service.context.workspace_id,
            RiskScan.content_id.in_(content_ids),
            RiskScan.platform == Content.platform,
        )
        .subquery()
    )
    scans = list(
        session.scalars(
            select(RiskScan)
            .join(
                latest_scan_rank,
                RiskScan.id == latest_scan_rank.c.id,
            )
            .where(latest_scan_rank.c.row_number == 1)
        )
    )
    latest_scans = {scan.content_id: scan for scan in scans}
    latest_cover_rank = (
        select(
            ContentAsset.id.label("id"),
            func.row_number().over(
                partition_by=ContentAsset.content_id,
                order_by=(
                    ContentAsset.created_at.desc(),
                    ContentAsset.id.desc(),
                ),
            ).label("row_number"),
        )
        .where(
            ContentAsset.workspace_id == service.context.workspace_id,
            ContentAsset.content_id.in_(content_ids),
            ContentAsset.category == AssetCategory.COVER,
        )
        .subquery()
    )
    covers = list(
        session.scalars(
            select(ContentAsset)
            .join(
                latest_cover_rank,
                ContentAsset.id == latest_cover_rank.c.id,
            )
            .where(latest_cover_rank.c.row_number == 1)
        )
    )
    latest_covers = {cover.content_id: cover for cover in covers}
    return [
        {
            "id": content.id,
            "title": content.title,
            "platform": content.platform.value,
            "account_id": content.account_id,
            "account_name": accounts[content.account_id].name,
            "column_campaign_id": content.column_campaign_id,
            "column_campaign_name": (
                columns[content.column_campaign_id].name
                if content.column_campaign_id is not None
                else None
            ),
            "content_type": content.content_type.value,
            "lifecycle_status": content.status.value,
            "published_at": content.published_at,
            "latest_maturity": (
                latest_snapshots[content.id].maturity_bucket
                if content.id in latest_snapshots
                else None
            ),
            "data_completeness": len(maturity_by_content[content.id]) / 4,
            "analysis_status": (
                latest_analyses[content.id].status.value
                if content.id in latest_analyses
                else "not_requested"
            ),
            "risk_status": _risk_status(latest_scans.get(content.id)),
            "cover": (
                _asset_payload(latest_covers[content.id], storage)
                if content.id in latest_covers
                else None
            ),
        }
        for content in contents
    ]


@workspace_content_router.get("", response_model=ContentListPageRead)
def list_workspace_contents(
    workspace_id: UUID,
    session: DatabaseSession,
    storage: ObjectStorage,
    platform: Platform | None = None,
    account_id: UUID | None = None,
    column_id: UUID | None = None,
    content_type: ContentType | None = None,
    status: Annotated[str | None, Query(pattern="^(draft|published|archived)$")] = None,
    maturity: Annotated[str | None, Query(pattern="^(1h|24h|72h|7d)$")] = None,
    query: Annotated[str | None, Query(max_length=300)] = None,
    sort: Annotated[
        str,
        Query(pattern="^(newest|oldest|title_asc|title_desc|published_desc)$"),
    ] = "newest",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    metric_key: Annotated[str | None, Query(max_length=80)] = None,
    required_metric_keys: Annotated[list[str] | None, Query()] = None,
    attention: Literal["candidate", "anomaly"] | None = None,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> dict:
    service = _service(
        session,
        session_token,
        None,
        mutation=False,
        workspace_id=workspace_id,
    )
    try:
        drill_down_requested = bool(
            metric_key or required_metric_keys or attention
        )
        if drill_down_requested and not (
            account_id and platform and content_type and maturity
        ):
            raise ValueError("drill-down filter is incomplete")
        allowed_content_ids = None
        if drill_down_requested:
            assert account_id is not None
            assert content_type is not None
            assert maturity is not None
            drill_down_items = DashboardService(
                session,
                service.context,
            ).drill_down(
                account_id,
                content_type=content_type,
                maturity_bucket=MaturityBucket(maturity),
                metric_key=metric_key,
                required_metric_keys=required_metric_keys or [],
                attention=attention,
            )
            allowed_content_ids = {
                item.content_id for item in drill_down_items
            }
        items, total = service.list_page(
            platform=platform,
            account_id=account_id,
            column_id=column_id,
            content_type=content_type,
            status=ContentStatus(status) if status else None,
            maturity=None if allowed_content_ids is not None else maturity,
            query=query.strip() if query and query.strip() else None,
            sort=sort,
            page=page,
            page_size=page_size,
            allowed_content_ids=allowed_content_ids,
        )
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail="resource not found") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "items": _list_items_payload(session, service, list(items), storage),
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


@workspace_content_router.get(
    "/{content_id}/detail",
    response_model=ContentDetailRead,
)
def read_workspace_content_detail(
    workspace_id: UUID,
    content_id: UUID,
    session: DatabaseSession,
    storage: ObjectStorage,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> dict:
    service = _service(
        session,
        session_token,
        None,
        mutation=False,
        workspace_id=workspace_id,
    )
    try:
        content = service.read(content_id)
        snapshot_service = SnapshotService(session, service.context)
        snapshots = list(
            reversed(
                list(
                    session.scalars(
                        select(DataSnapshot)
                        .where(
                            DataSnapshot.workspace_id == workspace_id,
                            DataSnapshot.content_id == content.id,
                        )
                        .order_by(
                            DataSnapshot.collected_at.desc(),
                            DataSnapshot.id.desc(),
                        )
                        .limit(100)
                    )
                )
            )
        )
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail="content not found") from error
    snapshot_values = list(
        session.scalars(
            select(SnapshotMetricValue)
            .where(
                SnapshotMetricValue.workspace_id == workspace_id,
                SnapshotMetricValue.snapshot_id.in_(
                    [snapshot.id for snapshot in snapshots]
                ),
            )
            .order_by(
                SnapshotMetricValue.snapshot_id,
                SnapshotMetricValue.created_at,
            )
        )
    ) if snapshots else []
    values_by_snapshot: dict[UUID, list[SnapshotMetricValue]] = {
        snapshot.id: [] for snapshot in snapshots
    }
    for value in snapshot_values:
        values_by_snapshot[value.snapshot_id].append(value)
    completeness = snapshot_service.completeness(content.id)
    analysis_runs = list(
        session.scalars(
            select(AnalysisRun)
            .where(
                AnalysisRun.workspace_id == workspace_id,
                AnalysisRun.content_id == content.id,
            )
            .order_by(AnalysisRun.created_at.desc(), AnalysisRun.id.desc())
            .limit(100)
        )
    )
    risk_scans = list(
        session.scalars(
            select(RiskScan)
            .where(
                RiskScan.workspace_id == workspace_id,
                RiskScan.content_id == content.id,
                RiskScan.platform == content.platform,
            )
            .order_by(RiskScan.created_at.desc(), RiskScan.id.desc())
            .limit(100)
        )
    )
    cover_runs = list(
        session.scalars(
            select(CoverGenerationRun)
            .where(
                CoverGenerationRun.workspace_id == workspace_id,
                CoverGenerationRun.content_id == content.id,
                CoverGenerationRun.platform == content.platform.value,
            )
            .order_by(
                CoverGenerationRun.created_at.desc(),
                CoverGenerationRun.id.desc(),
            )
            .limit(100)
        )
    )
    confirmed_snapshots = [snapshot for snapshot in snapshots if snapshot.confirmed]
    shared_metric_keys: set[str] | None = None
    for snapshot in confirmed_snapshots:
        current_keys = {
            value.metric_key
            for value in values_by_snapshot[snapshot.id]
            if value.normalized_value is not None
        }
        shared_metric_keys = (
            current_keys
            if shared_metric_keys is None
            else shared_metric_keys & current_keys
        )
    trend_metric = (
        sorted(shared_metric_keys)[0]
        if len(confirmed_snapshots) >= 2 and shared_metric_keys
        else None
    )
    if len(confirmed_snapshots) < 2:
        trend_reason = "至少需要两条已确认快照。"
    elif not shared_metric_keys:
        trend_reason = "快照之间缺少共同的有效规范化指标。"
    else:
        trend_reason = "已满足同一内容、同一平台、同一类型和同一指标口径。"
    successful_analysis = any(
        run.status.value == "succeeded" for run in analysis_runs
    )
    if content.status.value == "draft":
        lifecycle_stage = "灵感/选题"
    elif content.status.value == "published" and successful_analysis:
        lifecycle_stage = "已分析"
    elif content.status.value == "published" and snapshots:
        lifecycle_stage = "数据采集中"
    elif content.status.value == "published":
        lifecycle_stage = "已发布"
    else:
        lifecycle_stage = "未知"
    return {
        "content": _payload(session, content, storage),
        "lifecycle_stage": lifecycle_stage,
        "snapshots": [
            snapshot_service.read_payload(
                snapshot,
                completeness=completeness,
                values=values_by_snapshot[snapshot.id],
            )
            for snapshot in snapshots
        ],
        "snapshot_trend": {
            "eligible": trend_metric is not None,
            "reason": trend_reason,
            "metric_key": trend_metric,
            "points": [
                {
                    "snapshot_id": snapshot.id,
                    "collected_at": snapshot.collected_at,
                    "normalized_value": str(
                        next(
                            value.normalized_value
                            for value in values_by_snapshot[snapshot.id]
                            if value.metric_key == trend_metric
                        )
                    ),
                }
                for snapshot in confirmed_snapshots
            ] if trend_metric is not None else [],
        },
        "analysis_runs": analysis_runs,
        "risk_scans": [
            {
                "id": scan.id,
                "previous_scan_id": scan.previous_scan_id,
                "status": scan.status.value,
                "node": scan.node.value,
                "result": scan.result,
                "error_code": scan.error_code,
                "diagnostics": scan.diagnostics,
                "rule_version": scan.rule_version,
                "evidence_version": scan.evidence_version,
                "embedding_model_id": scan.embedding_model_id,
                "embedding_version": scan.embedding_version,
                "rag_model_version": scan.rag_model_version,
                "scanner_version": scan.scanner_version,
                "ocr_provider": scan.ocr_provider,
                "ocr_model_id": scan.ocr_model_id,
                "created_at": scan.created_at,
            }
            for scan in risk_scans
        ],
        "generation_records": [
            {
                "id": run.id,
                "kind": "cover",
                "status": run.status.value,
                "provider": run.provider,
                "model_id": run.model_id,
                "contract_version": run.contract_version,
                "account_style_version": None,
                "column_override_version": None,
                "confirmed_facts_version": None,
                "viral_reference_count": None,
                "preset_version": None,
                "original_result": None,
                "final_result": None,
                "adoption_status": None,
                "modification_magnitude": None,
                "created_at": run.created_at,
                "completed_at": run.completed_at,
            }
            for run in cover_runs
        ],
    }


@router.post("", response_model=ContentRead, status_code=201)
def create_content(
    data: ContentCreate,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict:
    service = _service(
        session,
        session_token,
        csrf_token,
        mutation=True,
        workspace_id=data.workspace_id,
    )
    try:
        content = service.create(
            account_id=data.account_id,
            platform=Platform(data.platform),
            content_type=ContentType(data.content_type),
            title=data.title,
            body=data.body,
            column_campaign_id=data.column_campaign_id,
            work_url=str(data.work_url) if data.work_url else None,
        )
        content.platform_content_id = data.platform_content_id
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    return _payload(session, content)


@router.get("", response_model=list[ContentRead])
def list_contents(
    workspace_id: UUID,
    session: DatabaseSession,
    storage: ObjectStorage,
    trash: bool = False,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> list[dict]:
    service = _service(
        session, session_token, None, mutation=False, workspace_id=workspace_id
    )
    try:
        contents = service.list(trash=trash)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    return [_payload(session, content, storage) for content in contents]


@router.get("/{content_id}", response_model=ContentRead)
def read_content(
    content_id: UUID,
    session: DatabaseSession,
    storage: ObjectStorage,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> dict:
    service = _service(session, session_token, None, mutation=False)
    try:
        content = service.read(content_id)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return _payload(session, content, storage)


@router.patch("/{content_id}", response_model=ContentRead)
def update_content(
    content_id: UUID,
    data: ContentUpdate,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict:
    service = _service(session, session_token, csrf_token, mutation=True)
    changes = data.model_dump(exclude_unset=True)
    if changes.get("work_url") is not None:
        changes["work_url"] = str(changes["work_url"])
    try:
        content = service.update(content_id, changes=changes)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    return _payload(session, content)


@router.delete("/{content_id}", status_code=204)
def delete_content(
    content_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> Response:
    service = _service(session, session_token, csrf_token, mutation=True)
    try:
        service.delete(content_id)
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    session.commit()
    return Response(status_code=204)


@router.post(
    "/{content_id}/assets/presign",
    response_model=AssetUploadGrantRead,
    status_code=201,
)
def presign_asset(
    content_id: UUID,
    data: AssetPresignRequest,
    session: DatabaseSession,
    storage: ObjectStorage,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict:
    service = _service(session, session_token, csrf_token, mutation=True)
    try:
        content = service.prepare_asset(content_id, AssetCategory(data.category))
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    grant = storage.issue_upload(
        workspace_id=content.workspace_id,
        content_id=content.id,
        category=data.category,
        file_name=data.file_name,
        mime_type=data.mime_type,
        size=data.size,
    )
    return {
        "object_key": grant.object_key,
        "upload_url": grant.upload_url,
        "upload_headers": grant.upload_headers,
        "upload_token": grant.upload_token,
        "expires_at": grant.expires_at,
    }


@router.post(
    "/{content_id}/assets/confirm",
    response_model=AssetRead,
    status_code=201,
)
def confirm_asset(
    content_id: UUID,
    data: AssetConfirmRequest,
    session: DatabaseSession,
    storage: ObjectStorage,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict:
    service = _service(session, session_token, csrf_token, mutation=True)
    try:
        metadata = storage.verify_upload_token(data.upload_token)
        if UUID(str(metadata["content_id"])) != content_id:
            raise InvalidUploadToken
        stored = storage.inspect_object(str(metadata["object_key"]))
        if stored is None:
            raise HTTPException(status_code=409, detail="uploaded object not found")
        if stored.size != int(metadata["size"]) or stored.mime_type != metadata["mime_type"]:
            raise HTTPException(status_code=409, detail="uploaded object metadata mismatch")
        asset = service.confirm_asset(
            content_id,
            category=AssetCategory(metadata["category"]),
            object_key=str(metadata["object_key"]),
            file_name=str(metadata["file_name"]),
            mime_type=str(metadata["mime_type"]),
            size=int(metadata["size"]),
        )
    except InvalidUploadToken as error:
        raise HTTPException(status_code=401, detail="invalid upload token") from error
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    session.commit()
    return _asset_payload(asset, storage)
