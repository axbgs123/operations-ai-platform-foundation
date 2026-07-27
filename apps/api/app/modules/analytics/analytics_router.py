from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.modules.analytics.north_star import (
    AnalyticsService,
    CompletenessResult,
    EffectiveWeeklyLoop,
    ProductMetrics,
    WeeklyRetention,
    calculate_weekly_retention,
)
from app.modules.workspace.auth import InviteAuthService


router = APIRouter(tags=["analytics"])
DatabaseSession = Annotated[Session, Depends(get_session)]


def _service(
    session: Session,
    session_token: str | None,
    workspace_id: UUID,
    *,
    admin_only: bool,
) -> AnalyticsService:
    if session_token is None:
        raise HTTPException(status_code=401, detail="invalid session")
    context = InviteAuthService(session).authenticate(session_token)
    if context is None:
        raise HTTPException(status_code=401, detail="invalid session")
    if context.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="workspace not found")
    if context.role == "demo":
        raise HTTPException(status_code=403, detail="demo metrics unavailable")
    if admin_only and context.role != "admin":
        raise HTTPException(status_code=403, detail="permission denied")
    return AnalyticsService(session, context)


@router.get(
    "/v1/workspaces/{workspace_id}/analytics/completeness",
    response_model=CompletenessResult,
)
def read_completeness(
    workspace_id: UUID,
    account_id: Annotated[UUID, Query()],
    session: DatabaseSession,
    content_id: Annotated[UUID | None, Query()] = None,
    session_token: Annotated[
        str | None,
        Cookie(alias="session"),
    ] = None,
):
    service = _service(
        session,
        session_token,
        workspace_id,
        admin_only=False,
    )
    try:
        return service.completeness(account_id, content_id=content_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get(
    "/v1/workspaces/{workspace_id}/analytics/product-metrics",
    response_model=ProductMetrics,
)
def read_product_metrics(
    workspace_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[
        str | None,
        Cookie(alias="session"),
    ] = None,
):
    return _service(
        session,
        session_token,
        workspace_id,
        admin_only=True,
    ).product_metrics()


@router.get(
    "/v1/workspaces/{workspace_id}/analytics/effective-loops",
    response_model=list[EffectiveWeeklyLoop],
)
def read_effective_loops(
    workspace_id: UUID,
    session: DatabaseSession,
    session_token: Annotated[
        str | None,
        Cookie(alias="session"),
    ] = None,
):
    return _service(
        session,
        session_token,
        workspace_id,
        admin_only=True,
    ).effective_loops()


@router.get(
    "/v1/workspaces/{workspace_id}/analytics/weekly-retention",
    response_model=WeeklyRetention,
)
def read_weekly_retention(
    workspace_id: UUID,
    baseline_week: Annotated[str, Query(pattern=r"^\d{4}-W\d{2}$")],
    return_week: Annotated[str, Query(pattern=r"^\d{4}-W\d{2}$")],
    session: DatabaseSession,
    session_token: Annotated[
        str | None,
        Cookie(alias="session"),
    ] = None,
):
    loops = _service(
        session,
        session_token,
        workspace_id,
        admin_only=True,
    ).effective_loops()
    # A single-workspace response is deliberately marked insufficient rather
    # than exposing a misleading cohort rate.
    result = calculate_weekly_retention(
        baseline_week=baseline_week,
        return_week=return_week,
        loops=loops,
    )
    if result.denominator < 5:
        return WeeklyRetention(
            status="INSUFFICIENT_SAMPLE",
            baseline_week=baseline_week,
            return_week=return_week,
            denominator=result.denominator,
            returned_workspaces=0,
            rate=None,
        )
    return result
