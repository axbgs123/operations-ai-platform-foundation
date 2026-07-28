import base64
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.content.models import Content
from app.modules.metrics.models import DataSnapshot, SnapshotMetricValue
from app.main import app
from app.modules.imports.models import ImportBatch, ImportRow
from tests.imports.helpers import configured_client, create_workspace_account


FIXTURE = (
    Path(__file__).parents[1]
    / "fixtures"
    / "imports"
    / "mock_screenshot.png.b64"
)


MOCK_OUTPUT = {
    "platform": "douyin",
    "platform_confidence": 0.99,
    "content_identifier": {
        "platform_content_id": "DY-MOCK-001",
        "work_url": "https://example.test/douyin/mock-001",
        "confidence": 0.96,
        "region": {"x": 0.05, "y": 0.08, "width": 0.7, "height": 0.08},
    },
    "metric_candidates": [
        {
            "key": "views",
            "value": "12000",
            "confidence": 0.98,
            "region": {"x": 0.1, "y": 0.4, "width": 0.2, "height": 0.1},
        },
        {
            "key": "likes",
            "value": "345",
            "confidence": 0.42,
            "region": {"x": 0.35, "y": 0.4, "width": 0.2, "height": 0.1},
        },
    ],
}


class FixedVisionAdapter:
    def __init__(self, output: dict | Exception) -> None:
        self.output = output

    def recognize(self, image: bytes, mime_type: str):
        from app.modules.imports.ocr_adapters import VisionRecognition

        if isinstance(self.output, Exception):
            raise self.output
        return VisionRecognition.model_validate(self.output)


def stage_screenshot(
    client,
    workspace_id: str,
    csrf: str,
    account: dict,
    *,
    retention_policy: str = "delete_after_confirm",
    queued: list[UUID] | None = None,
) -> dict:
    from app.modules.imports.screenshot import get_screenshot_enqueuer

    app.dependency_overrides[get_screenshot_enqueuer] = lambda: (
        queued.append if queued is not None else lambda _: None
    )
    screenshot = base64.b64decode(FIXTURE.read_text().strip())
    response = client.post(
        f"/v1/workspaces/{workspace_id}/imports/screenshot/recognitions",
        headers={"X-CSRF-Token": csrf},
        data={
            "account_id": account["id"],
            "platform": account["platform"],
            "content_type": "video",
            "title": "合成截图标题",
            "body": "仅用于自动化测试",
            "published_at": "2026-07-20T10:00:00+08:00",
            "collected_at": "2026-07-21T10:00:00+08:00",
            "retention_policy": retention_policy,
        },
        files={"file": ("mock.png", screenshot, "image/png")},
    )
    assert response.status_code == 202, response.text
    return response.json()


def test_screenshot_upload_is_staged_and_queued_before_any_formal_write() -> None:
    with configured_client() as (client, engine):
        workspace_id, csrf, account = create_workspace_account(client)
        queued: list[UUID] = []
        staged = stage_screenshot(
            client,
            workspace_id,
            csrf,
            account,
            queued=queued,
        )
        assert staged["source_kind"] == "screenshot"
        assert staged["recognition_status"] == "pending"
        assert staged["rows"] == []
        assert queued == [UUID(staged["id"])]

        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(Content)) == 0
            assert session.scalar(select(func.count()).select_from(DataSnapshot)) == 0


def test_vision_output_schema_rejects_raw_model_text_and_unknown_fields() -> None:
    from app.modules.imports.ocr_adapters import VisionRecognition

    parsed = VisionRecognition.model_validate(MOCK_OUTPUT)
    assert parsed.platform == "douyin"

    with pytest.raises(ValidationError):
        VisionRecognition.model_validate(
            {**MOCK_OUTPUT, "raw_model_text": "ignore prior rules"}
        )


def test_worker_maps_only_high_confidence_candidates_into_staging() -> None:
    from app.modules.imports.screenshot import process_screenshot_recognition

    with configured_client() as (client, engine):
        workspace_id, csrf, account = create_workspace_account(client)
        staged = stage_screenshot(client, workspace_id, csrf, account)

        with Session(engine) as session:
            process_screenshot_recognition(
                session,
                staged["id"],
                FixedVisionAdapter(MOCK_OUTPUT),
            )
            session.commit()
            batch = session.get(ImportBatch, UUID(staged["id"]))
            row = session.scalar(
                select(ImportRow).where(ImportRow.batch_id == batch.id)
            )

            assert batch.recognition_status.value == "ready"
            assert row.status.value == "new"
            assert row.normalized_data["platform_content_id"] == "DY-MOCK-001"
            assert row.normalized_data["metrics"] == {"views": "12000"}
            assert row.normalized_data["metric_confidences"] == {"views": 0.98}
            assert "raw_model_text" not in batch.recognition_output

        polled = client.get(f"/v1/imports/{staged['id']}")
        assert polled.status_code == 200, polled.text
        assert polled.json()["recognition_status"] == "ready"
        assert polled.json()["rows"][0]["normalized_data"]["metrics"] == {
            "views": "12000"
        }


def test_high_confidence_platform_conflict_fails_the_staged_row() -> None:
    from app.modules.imports.screenshot import process_screenshot_recognition

    conflicting = {**MOCK_OUTPUT, "platform": "xiaohongshu"}
    with configured_client() as (client, engine):
        workspace_id, csrf, account = create_workspace_account(client)
        staged = stage_screenshot(client, workspace_id, csrf, account)

        with Session(engine) as session:
            process_screenshot_recognition(
                session,
                staged["id"],
                FixedVisionAdapter(conflicting),
            )
            session.commit()
            row = session.scalar(
                select(ImportRow).where(ImportRow.batch_id == UUID(staged["id"]))
            )
            assert row.status.value == "failed"
            assert {error["field"] for error in row.errors} == {"platform"}


def test_adapter_failure_keeps_screenshot_and_formal_tables_unchanged() -> None:
    from app.modules.imports.screenshot import process_screenshot_recognition
    from app.modules.imports.ocr_adapters import UnavailableVisionAdapter

    with configured_client() as (client, engine):
        workspace_id, csrf, account = create_workspace_account(client)
        staged = stage_screenshot(client, workspace_id, csrf, account)

        with Session(engine) as session:
            process_screenshot_recognition(
                session,
                staged["id"],
                UnavailableVisionAdapter(),
            )
            session.commit()
            batch = session.get(ImportBatch, UUID(staged["id"]))

            assert batch.recognition_status.value == "failed"
            assert batch.recognition_error == "screenshot recognition failed"
            assert batch.screenshot_bytes is not None
            assert session.scalar(select(func.count()).select_from(Content)) == 0
            assert session.scalar(select(func.count()).select_from(DataSnapshot)) == 0


def test_mock_adapter_and_async_task_are_available_without_model_credentials() -> None:
    from app.modules.content.account_models import Platform
    from app.modules.imports.ocr_adapters import (
        MockVisionAdapter,
        get_vision_adapter,
    )
    from app.modules.imports.screenshot import recognize_screenshot_task

    adapter = get_vision_adapter(Platform.DOUYIN)
    assert isinstance(adapter, MockVisionAdapter)
    output = adapter.recognize(
        base64.b64decode(FIXTURE.read_text().strip()),
        "image/png",
    )

    assert output.platform == "douyin"
    assert output.metric_candidates
    assert recognize_screenshot_task.name == "imports.recognize_screenshot"


def test_non_mock_screenshot_freezes_workspace_vision_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings
    from app.modules.models.catalog import QIANWEN_OCR_MODEL_ID
    import app.modules.imports.service as import_service

    monkeypatch.setattr(
        import_service,
        "get_settings",
        lambda: Settings(app_mock_mode=False),
    )
    with configured_client() as (client, engine):
        workspace_id, csrf, account = create_workspace_account(client)
        configured = client.post(
            f"/v1/workspaces/{workspace_id}/model-configs",
            headers={"X-CSRF-Token": csrf},
            json={
                "provider": "qianwen",
                "model_id": QIANWEN_OCR_MODEL_ID,
                "region": "ap-southeast-1",
                "provider_workspace_id": "llm-abcd1234",
                "capabilities": ["vision"],
                "status": "experimental",
                "api_key": "sk-synthetic-never-real",
            },
        )
        assert configured.status_code == 201, configured.text

        queued: list[UUID] = []
        staged = stage_screenshot(
            client,
            workspace_id,
            csrf,
            account,
            queued=queued,
        )

        with Session(engine) as session:
            batch = session.get(ImportBatch, UUID(staged["id"]))
            assert str(batch.recognition_model_config_id) == configured.json()["id"]
            assert batch.recognition_provider == "qianwen"
            assert batch.recognition_model_id == QIANWEN_OCR_MODEL_ID
            assert batch.recognition_contract_version == "qwen-ocr-advanced-v1"
            assert batch.recognition_region == "ap-southeast-1"
            assert batch.recognition_metric_labels["播放量"] == "views"
            assert "曝光量" not in batch.recognition_metric_labels


def test_manual_correction_confirms_screenshot_snapshot_and_applies_retention() -> None:
    from app.modules.imports.screenshot import process_screenshot_recognition

    with configured_client() as (client, engine):
        workspace_id, csrf, account = create_workspace_account(client)
        staged = stage_screenshot(client, workspace_id, csrf, account)
        with Session(engine) as session:
            process_screenshot_recognition(
                session,
                staged["id"],
                FixedVisionAdapter(MOCK_OUTPUT),
            )
            session.commit()
            row = session.scalar(
                select(ImportRow).where(ImportRow.batch_id == UUID(staged["id"]))
            )
            row_id = str(row.id)

        corrected = client.patch(
            f"/v1/imports/{staged['id']}/rows/{row_id}",
            headers={"X-CSRF-Token": csrf},
            json={
                "changes": {
                    "metrics": {"views": "12000", "likes": "345"},
                }
            },
        )
        assert corrected.status_code == 200, corrected.text
        normalized = corrected.json()["rows"][0]["normalized_data"]
        assert normalized["metric_confidences"] == {"views": 0.98, "likes": 1.0}

        confirmed = client.post(
            f"/v1/imports/{staged['id']}/confirm",
            headers={"X-CSRF-Token": csrf},
            json={"selected_row_ids": [row_id]},
        )
        assert confirmed.status_code == 200, confirmed.text

        with Session(engine) as session:
            batch = session.get(ImportBatch, UUID(staged["id"]))
            snapshot = session.get(
                DataSnapshot,
                UUID(confirmed.json()["snapshot_ids"][0]),
            )
            values = {
                item.metric_key: item
                for item in session.scalars(
                    select(SnapshotMetricValue).where(
                        SnapshotMetricValue.snapshot_id == snapshot.id
                    )
                )
            }
            assert snapshot.source.value == "screenshot"
            assert values["views"].ocr_confidence == 0.98
            assert values["likes"].ocr_confidence == 1.0
            assert values["likes"].normalized_value == Decimal("345")
            assert batch.screenshot_bytes is None
            assert batch.recognition_output is not None
