from __future__ import annotations

import json
import logging
import re
import secrets
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import PurePath
from typing import Any
from urllib.parse import unquote

from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import get_settings
from app.core.observability import technical_metrics


REDACTED = "[REDACTED]"
EVENT_VERSION = "1"
LOG_FIELDS = (
    "event_version",
    "timestamp",
    "level",
    "event",
    "message_code",
    "request_id",
    "task_id",
    "workspace_id",
    "member_id",
    "route_template",
    "method",
    "status_code",
    "duration_ms",
    "task_type",
    "task_status",
    "retry_count",
    "error_code",
    "provider",
    "model_id",
    "model_contract_version",
    "embedding_dimension",
    "input_count",
    "provider_request_id",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "latency_ms",
    "attempt",
    "service_name",
    "environment",
    "application_version",
)
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,63}$")
_SENSITIVE_PARTS = (
    "authorization",
    "bearer",
    "cookie",
    "csrf",
    "invite",
    "access_code",
    "token",
    "secret",
    "api_key",
    "apikey",
    "password",
    "hash",
    "database_url",
    "connection_string",
    "prompt",
    "model_response",
    "response_body",
    "request_body",
    "title",
    "copy",
    "content",
    "document",
    "screenshot",
    "image",
    "video",
    "audio",
    "base64",
    "multipart",
    "download_url",
    "signed_url",
    "query",
    "embedding",
    "vector",
    "backup",
    "archive",
    "delete_confirmation",
)
_LOW_SENSITIVITY_TELEMETRY_KEYS = {
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
}
_current_request_id: ContextVar[str | None] = ContextVar(
    "request_id",
    default=None,
)
_logger = logging.getLogger("operations_ai")

# httpx's INFO access log includes complete request URLs. Provider endpoints
# contain a private workspace identifier and image-result URLs are temporary
# signed capabilities, so only the structured, allowlisted adapter telemetry
# may be emitted at INFO.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


def validate_request_id(value: str | None) -> bool:
    return value is not None and _REQUEST_ID.fullmatch(value) is not None


def new_request_id() -> str:
    return f"req_{secrets.token_hex(16)}"


def current_request_id() -> str:
    value = _current_request_id.get()
    return value or new_request_id()


@contextmanager
def task_request_context(request_id: str | None):
    safe_request_id = (
        request_id if validate_request_id(request_id) else new_request_id()
    )
    token = _current_request_id.set(safe_request_id)
    try:
        yield safe_request_id
    finally:
        _current_request_id.reset(token)


def _sensitive_key(key: object) -> bool:
    normalized = str(key).lower().replace("-", "_")
    if normalized in _LOW_SENSITIVITY_TELEMETRY_KEYS:
        return False
    return any(part in normalized for part in _SENSITIVE_PARTS)


def _safe_file_name(value: object) -> str:
    raw = re.sub(r"[\x00-\x1f\x7f]", "", str(value))
    return PurePath(raw.replace("\\", "/")).name[:180]


def _safe_error_code(error: BaseException) -> str:
    name = error.__class__.__name__
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).upper()[:80]


def sanitize_context(value: Any, *, key: str | None = None) -> Any:
    if key is not None and key.lower().replace("-", "_") in {
        "file_name",
        "filename",
    }:
        return _safe_file_name(value)
    if key is not None and _sensitive_key(key):
        return REDACTED
    if isinstance(value, BaseException):
        return {"error_code": _safe_error_code(value)}
    if isinstance(value, dict):
        return {
            str(item_key): sanitize_context(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [sanitize_context(item) for item in value]
    if isinstance(value, str):
        decoded = unquote(value)
        if re.search(
            r"(?i)(bearer\s+|authorization[=:]|cookie[=:]|"
            r"x-amz-signature=|password[=:]|api[_-]?key[=:])",
            decoded,
        ):
            return REDACTED
        return re.sub(r"[\x00-\x1f\x7f]", "", value)[:500]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:200]


def build_log_event(
    *,
    level: str = "INFO",
    timestamp: datetime | None = None,
    **values: object,
) -> dict[str, object]:
    settings = get_settings()
    defaults: dict[str, object] = {
        "event_version": EVENT_VERSION,
        "timestamp": (timestamp or datetime.now(UTC)).isoformat(),
        "level": level.upper(),
        "service_name": "operations-ai-api",
        "environment": settings.app_env,
        "application_version": "0.1.0",
    }
    result: dict[str, object] = {}
    for field in LOG_FIELDS:
        candidate = values.get(field, defaults.get(field))
        if candidate is not None:
            result[field] = sanitize_context(candidate, key=field)
    return result


def emit_log(logger: logging.Logger, **values: object) -> None:
    try:
        event = build_log_event(**values)  # type: ignore[arg-type]
        logger.log(
            getattr(logging, str(event.get("level", "INFO")), logging.INFO),
            json.dumps(event, ensure_ascii=False, separators=(",", ":")),
        )
    except Exception:
        logger.warning(
            '{"level":"WARNING","event":"log.serialization_failed",'
            '"message_code":"LOG_SERIALIZATION_FAILED"}'
        )


class RequestCorrelationMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", ())
        }
        supplied = headers.get("x-request-id")
        if supplied is not None and not validate_request_id(supplied):
            safe_id = new_request_id()
            response = JSONResponse(
                status_code=400,
                content={
                    "detail": {
                        "code": "INVALID_REQUEST_ID",
                        "message": "invalid request correlation identifier",
                    }
                },
                headers={"X-Request-ID": safe_id},
            )
            await response(scope, receive, send)
            return
        request_id = supplied or new_request_id()
        started = time.monotonic()
        status_code = 500
        token = _current_request_id.set(request_id)
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers_list = list(message.get("headers", []))
                headers_list.append((b"x-request-id", request_id.encode("ascii")))
                message["headers"] = headers_list
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            duration_ms = round((time.monotonic() - started) * 1000, 3)
            route = scope.get("route")
            route_template = getattr(route, "path", "unmatched")
            emit_log(
                _logger,
                event="http.request.completed",
                message_code="HTTP_REQUEST_COMPLETED",
                request_id=request_id,
                route_template=route_template,
                method=scope.get("method", "GET"),
                status_code=status_code,
                duration_ms=duration_ms,
            )
            technical_metrics.record(
                "http_requests_total",
                labels={
                    "method": str(scope.get("method", "GET")),
                    "route": str(route_template),
                    "status_class": f"{status_code // 100}xx",
                },
            )
            technical_metrics.record(
                "http_request_duration_ms",
                duration_ms,
                labels={
                    "method": str(scope.get("method", "GET")),
                    "route": str(route_template),
                },
            )
            _current_request_id.reset(token)
