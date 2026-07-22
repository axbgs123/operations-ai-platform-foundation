from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.modules.metrics.dashboard import (
    AccountDashboard,
    DashboardContentItem,
    DashboardService,
)
from app.modules.metrics.maturity import MaturityBucket
from app.modules.metrics.models import ContentType
from app.modules.workspace.auth import InviteAuthService
from app.modules.workspace.permissions import PermissionDenied


router = APIRouter(tags=["dashboard"])
DatabaseSession = Annotated[Session, Depends(get_session)]


@router.get(
    "/v1/workspaces/{workspace_id}/accounts/{account_id}/dashboard",
    response_model=AccountDashboard,
)
def read_account_dashboard(
    workspace_id: UUID,
    account_id: UUID,
    content_type: ContentType,
    maturity_bucket: MaturityBucket,
    session: DatabaseSession,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> AccountDashboard:
    if session_token is None:
        raise HTTPException(status_code=401, detail="invalid session")
    context = InviteAuthService(session).authenticate(session_token)
    if context is None:
        raise HTTPException(status_code=401, detail="invalid session")
    if context.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="workspace not found")
    try:
        return DashboardService(session, context).build(
            account_id,
            content_type=content_type,
            maturity_bucket=maturity_bucket,
        )
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get(
    "/v1/workspaces/{workspace_id}/accounts/{account_id}/dashboard/contents",
    response_model=list[DashboardContentItem],
)
def read_dashboard_contents(
    workspace_id: UUID,
    account_id: UUID,
    content_type: ContentType,
    maturity_bucket: MaturityBucket,
    session: DatabaseSession,
    metric_key: str | None = None,
    required_metric_keys: Annotated[list[str] | None, Query()] = None,
    attention: Literal["candidate", "anomaly"] | None = None,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> list[DashboardContentItem]:
    if session_token is None:
        raise HTTPException(status_code=401, detail="invalid session")
    context = InviteAuthService(session).authenticate(session_token)
    if context is None:
        raise HTTPException(status_code=401, detail="invalid session")
    if context.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="workspace not found")
    try:
        return DashboardService(session, context).drill_down(
            account_id,
            content_type=content_type,
            maturity_bucket=maturity_bucket,
            metric_key=metric_key,
            required_metric_keys=required_metric_keys or [],
            attention=attention,
        )
    except PermissionDenied as error:
        raise HTTPException(status_code=403, detail="permission denied") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
