from typing import Annotated, Any

from fastapi import APIRouter, Cookie, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.modules.demo.service import DemoLimitReached, DemoService, DemoSessionInvalid


router = APIRouter(prefix="/v1/demo", tags=["demo"])
demo_service = DemoService()


class DemoGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=1_000)


class DemoGenerateResponse(BaseModel):
    content: str
    label: str = "Mock 输出"
    mock: bool = True
    session_remaining: int
    ip_remaining: int


@router.get("/workspace")
def read_demo_workspace() -> dict[str, Any]:
    return demo_service.workspace()


@router.post("/sessions", status_code=201)
def create_demo_session(response: Response) -> dict[str, int]:
    token = demo_service.create_session()
    response.set_cookie(
        key="demo_session",
        value=token,
        max_age=int(demo_service.session_lifetime.total_seconds()),
        httponly=True,
        secure=get_settings().app_env != "development",
        samesite="lax",
        path="/v1/demo",
    )
    return {"generation_limit": demo_service.session_limit}


@router.post("/generations", response_model=DemoGenerateResponse)
def create_demo_generation(
    data: DemoGenerateRequest,
    request: Request,
    demo_session: Annotated[str | None, Cookie()] = None,
) -> DemoGenerateResponse:
    if demo_session is None:
        raise HTTPException(status_code=401, detail="demo session required")
    try:
        generated = demo_service.generate(
            demo_session,
            request.client.host if request.client else "unknown",
            data.prompt,
        )
    except DemoSessionInvalid as error:
        raise HTTPException(status_code=401, detail="demo session expired") from error
    except DemoLimitReached as error:
        raise HTTPException(
            status_code=429,
            detail="demo generation limit reached",
        ) from error
    return DemoGenerateResponse(
        content=generated.content,
        session_remaining=generated.session_remaining,
        ip_remaining=generated.ip_remaining,
    )


@router.post("/uploads", status_code=403)
def reject_demo_upload() -> None:
    raise HTTPException(status_code=403, detail="uploads are disabled in demo")


@router.patch("/workspace", status_code=403)
def reject_demo_mutation() -> None:
    raise HTTPException(status_code=403, detail="demo seed data is read-only")
