import os
import secrets
from uuid import UUID

from fastapi import Header, HTTPException
from starlette.requests import Request

from app.core.database import SessionFactory
from app.core.config import get_settings
from app.core.storage import get_storage
from app.main import app
from app.modules.imports.capture_models import CaptureTask
from app.modules.imports.capture_service import object_digest


_session_events: list[dict[str, object]] = []


@app.middleware("http")
async def record_extension_session_events(request: Request, call_next):
    response = await call_next(request)
    if request.url.path in {
        "/v1/extension/session/challenge",
        "/v1/extension/session/renew",
    }:
        _session_events.append({
            "path": request.url.path,
            "status": response.status_code,
        })
    return response


@app.get("/__e2e/extension-session-events")
def extension_session_events(
    x_e2e_secret: str | None = Header(default=None, alias="X-E2E-Secret"),
) -> dict[str, object]:
    expected = os.environ.get("EXTENSION_E2E_SECRET", "")
    if (
        not expected
        or x_e2e_secret is None
        or not secrets.compare_digest(x_e2e_secret, expected)
    ):
        raise HTTPException(status_code=404, detail="not found")
    return {"events": list(_session_events)}


@app.get("/__e2e/capture-object/{workspace_id}/{task_id}")
def inspect_capture_object(
    workspace_id: UUID,
    task_id: UUID,
    x_e2e_secret: str | None = Header(default=None, alias="X-E2E-Secret"),
) -> dict[str, object]:
    expected = os.environ.get("EXTENSION_E2E_SECRET", "")
    if not expected or x_e2e_secret is None or not secrets.compare_digest(x_e2e_secret, expected):
        raise HTTPException(status_code=404, detail="not found")
    with SessionFactory() as session:
        task = session.get(CaptureTask, task_id)
        if task is None or task.workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail="not found")
        present = (
            object_digest(task) is not None
            if get_settings().app_mock_mode
            else get_storage().inspect_object(task.object_key) is not None
        )
        return {
            "present": present,
            "prefix_matches": task.object_key.startswith(
                f"workspaces/{workspace_id}/capture/"
            ),
        }
