from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.modules.content.account_router import router as account_router
from app.modules.content.router import router as content_router
from app.modules.demo.router import router as demo_router
from app.modules.imports.router import router as imports_router
from app.modules.metrics.dashboard_router import router as dashboard_router
from app.modules.metrics.router import router as metrics_router
from app.modules.workspace.router import router as workspace_router

app = FastAPI(title="Operations AI Platform API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().web_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)
app.include_router(workspace_router)
app.include_router(demo_router)
app.include_router(imports_router)
app.include_router(account_router)
app.include_router(content_router)
app.include_router(metrics_router)
app.include_router(dashboard_router)


@app.get("/healthz")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
