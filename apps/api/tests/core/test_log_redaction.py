import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.logging import (
    REDACTED,
    RequestCorrelationMiddleware,
    build_log_event,
    sanitize_context,
    task_request_context,
    validate_request_id,
)


def test_structured_log_uses_whitelist_and_recursively_redacts_secrets() -> None:
    secret = "invite-secret-value"
    event = build_log_event(
        event="request.completed",
        message_code="REQUEST_COMPLETED",
        request_id="req_01JSAFE000000000000000000",
        method="POST",
        status_code=200,
        authorization=f"bEaReR {secret}",
        cookie=f"session={secret}",
        nested={"api_KEY": secret},
        title="完整敏感标题",
    )

    rendered = json.dumps(event, ensure_ascii=False)

    assert list(event) == [
        "event_version",
        "timestamp",
        "level",
        "event",
        "message_code",
        "request_id",
        "method",
        "status_code",
        "service_name",
        "environment",
        "application_version",
    ]
    assert secret not in rendered
    assert "完整敏感标题" not in rendered


def test_context_redaction_handles_nested_urls_encoded_values_and_exceptions() -> None:
    secret = "token-with-private-value"
    value = {
        "safe": "ok",
        "Authorization": f"Bearer%20{secret}",
        "items": [
            {"prompt": "完整提示词", "download_url": f"https://s3.test/x?sig={secret}"},
            ValueError(f"provider returned Cookie={secret}"),
        ],
        "vector": [0.1, 0.2],
        "file_name": "../private\r\nSet-Cookie.txt",
    }

    safe = sanitize_context(value)
    rendered = json.dumps(safe, ensure_ascii=False)

    assert safe["safe"] == "ok"
    assert safe["Authorization"] == REDACTED
    assert safe["items"][0]["prompt"] == REDACTED
    assert safe["items"][0]["download_url"] == REDACTED
    assert safe["items"][1] == {"error_code": "VALUE_ERROR"}
    assert safe["vector"] == REDACTED
    assert safe["file_name"] == "privateSet-Cookie.txt"
    assert secret not in rendered


def test_request_id_validation_rejects_control_characters_and_unsafe_shapes() -> None:
    assert validate_request_id("req_01JSAFE000000000000000000")
    assert not validate_request_id("short")
    assert not validate_request_id("req_good\nAuthorization: Bearer secret")
    assert not validate_request_id("x" * 65)


def test_request_middleware_generates_or_propagates_only_safe_request_ids() -> None:
    app = FastAPI()
    app.add_middleware(RequestCorrelationMiddleware)

    @app.get("/probe")
    def probe() -> dict[str, str]:
        from app.core.logging import current_request_id

        return {"request_id": current_request_id()}

    client = TestClient(app)
    accepted = client.get(
        "/probe",
        headers={"X-Request-ID": "req_01JSAFE000000000000000000"},
    )
    rejected = client.get("/probe", headers={"X-Request-ID": "bad\nvalue"})

    assert accepted.headers["X-Request-ID"] == "req_01JSAFE000000000000000000"
    assert accepted.json()["request_id"] == accepted.headers["X-Request-ID"]
    assert rejected.status_code == 400
    assert rejected.json()["detail"]["code"] == "INVALID_REQUEST_ID"


def test_task_context_preserves_original_request_id_and_replaces_invalid_values() -> (
    None
):
    from app.core.logging import current_request_id

    with task_request_context("req_01JSAFE000000000000000000"):
        assert current_request_id() == "req_01JSAFE000000000000000000"
    with task_request_context("Bearer secret"):
        assert current_request_id().startswith("req_")
        assert "secret" not in current_request_id()
