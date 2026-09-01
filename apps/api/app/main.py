from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings, get_settings
from app.core.logging import RequestCorrelationMiddleware
from app.core.operations_router import router as operations_router
from app.core.rate_limit import RateLimitMiddleware
from app.core.storage_router import router as local_storage_router
from app.modules.analysis.viral_router import router as viral_router
from app.modules.analysis.router import router as analysis_router
from app.modules.content.account_router import router as account_router
from app.modules.content.router import (
    router as content_router,
    workspace_content_router,
)
from app.modules.demo.router import router as demo_router
from app.modules.exports.router import router as exports_router
from app.modules.imports.extension_router import router as extension_router
from app.modules.imports.extension_router import review_router as extension_review_router
from app.modules.imports.router import router as imports_router
from app.modules.metrics.dashboard_router import router as dashboard_router
from app.modules.metrics.router import router as metrics_router
from app.modules.models.router import router as model_configs_router
from app.modules.operations_agent.router import router as operations_agent_router
from app.modules.risk_rag.router import scan_router as risk_scans_router
from app.modules.style_facts.style_router import router as style_profiles_router
from app.modules.style_facts.fact_router import router as fact_sources_router
from app.modules.generation.router import router as generation_router
from app.modules.hotspots.router import (
    extension_router as extension_hotspots_router,
    router as hotspots_router,
)
from app.modules.workspace.router import router as workspace_router
from app.modules.workbench.router import router as workbench_router

def create_app(settings: Settings | None = None) -> FastAPI:
    runtime_settings = settings or get_settings()
    application = FastAPI(title="Operations AI Platform API")
    application.add_middleware(RateLimitMiddleware)
    application.add_middleware(RequestCorrelationMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            runtime_settings.web_origin,
            runtime_settings.extension_origin,
        ],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "X-CSRF-Token",
            "X-Extension-Client",
            "X-Request-ID",
            "X-Workspace-Resume",
        ],
        expose_headers=["X-Request-ID", "Retry-After"],
    )

    # Core operator workflows remain available in both editions.
    application.include_router(workspace_router)
    application.include_router(local_storage_router)
    application.include_router(workbench_router)
    application.include_router(operations_agent_router)
    application.include_router(demo_router)
    application.include_router(exports_router)
    application.include_router(imports_router)
    application.include_router(extension_router)
    application.include_router(extension_review_router)
    application.include_router(account_router)
    application.include_router(content_router)
    application.include_router(workspace_content_router)
    application.include_router(metrics_router)
    application.include_router(model_configs_router)
    application.include_router(style_profiles_router)
    application.include_router(fact_sources_router)
    application.include_router(dashboard_router)
    application.include_router(viral_router)
    application.include_router(analysis_router)
    application.include_router(generation_router)
    application.include_router(hotspots_router)
    application.include_router(extension_hotspots_router)
    application.include_router(risk_scans_router)
    application.include_router(operations_router)

    # Advanced governance and recovery APIs are intentionally absent from the
    # Lite runtime. Keeping them out of the route table avoids advertising
    # workflows that require the full Redis/S3/worker deployment.
    if not runtime_settings.app_lite_mode:
        from app.modules.analytics.analytics_router import router as analytics_router
        from app.modules.exports.deletion_router import router as deletion_router
        from app.modules.exports.router import restore_router, zip_restore_router
        from app.modules.models.router import usage_router as model_usage_router
        from app.modules.risk_rag.router import (
            evaluation_router,
            feedback_router,
            feedback_scan_router,
            router as risk_documents_router,
        )

        application.include_router(restore_router)
        application.include_router(zip_restore_router)
        application.include_router(deletion_router)
        application.include_router(model_usage_router)
        application.include_router(analytics_router)
        application.include_router(risk_documents_router)
        application.include_router(feedback_scan_router)
        application.include_router(feedback_router)
        application.include_router(evaluation_router)

    @application.get("/healthz")
    def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()
