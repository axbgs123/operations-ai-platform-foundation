from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.logging import RequestCorrelationMiddleware
from app.core.operations_router import router as operations_router
from app.core.rate_limit import RateLimitMiddleware
from app.modules.analysis.viral_router import router as viral_router
from app.modules.analysis.router import router as analysis_router
from app.modules.analytics.analytics_router import router as analytics_router
from app.modules.content.account_router import router as account_router
from app.modules.content.router import router as content_router
from app.modules.demo.router import router as demo_router
from app.modules.exports.router import (
    restore_router,
    router as exports_router,
    zip_restore_router,
)
from app.modules.exports.deletion_router import router as deletion_router
from app.modules.imports.extension_router import router as extension_router
from app.modules.imports.extension_router import review_router as extension_review_router
from app.modules.imports.router import router as imports_router
from app.modules.metrics.dashboard_router import router as dashboard_router
from app.modules.metrics.router import router as metrics_router
from app.modules.models.router import router as model_configs_router
from app.modules.risk_rag.router import (
    router as risk_documents_router,
    scan_router as risk_scans_router,
    feedback_scan_router,
    feedback_router,
    evaluation_router,
)
from app.modules.style_facts.style_router import router as style_profiles_router
from app.modules.style_facts.fact_router import router as fact_sources_router
from app.modules.generation.router import router as generation_router
from app.modules.workspace.router import router as workspace_router

app = FastAPI(title="Operations AI Platform API")
app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestCorrelationMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().web_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Idempotency-Key",
        "X-CSRF-Token",
        "X-Extension-Client",
        "X-Request-ID",
    ],
    expose_headers=["X-Request-ID", "Retry-After"],
)
app.include_router(workspace_router)
app.include_router(demo_router)
app.include_router(exports_router)
app.include_router(restore_router)
app.include_router(zip_restore_router)
app.include_router(deletion_router)
app.include_router(imports_router)
app.include_router(extension_router)
app.include_router(extension_review_router)
app.include_router(account_router)
app.include_router(content_router)
app.include_router(metrics_router)
app.include_router(model_configs_router)
app.include_router(style_profiles_router)
app.include_router(fact_sources_router)
app.include_router(dashboard_router)
app.include_router(viral_router)
app.include_router(analysis_router)
app.include_router(analytics_router)
app.include_router(generation_router)
app.include_router(risk_documents_router)
app.include_router(risk_scans_router)
app.include_router(feedback_scan_router)
app.include_router(feedback_router)
app.include_router(evaluation_router)
app.include_router(operations_router)


@app.get("/healthz")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
