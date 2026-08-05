from uuid import UUID

from sqlalchemy.orm import Session

import pytest

from app.core.security import WorkspaceContext
from app.modules.models.models import ModelConfig, ModelConfigStatus
from app.modules.operations_agent.briefing import BriefingService
from app.modules.operations_agent.models import AgentEvent
from app.modules.risk_rag.models import (
    RiskScan,
    RiskScanNode,
    RiskScanStatus,
)
from app.modules.workspace.models import WorkspaceMember
from tests.imports.helpers import (
    configured_client,
    create_published_content,
    create_workspace_account,
    preview_manual,
)
from tests.workbench.test_workbench_api import _seeded_workbench


def _add_permission_failure_scan(
    session: Session,
    *,
    seeded: dict,
) -> None:
    session.add(
        RiskScan(
            workspace_id=UUID(seeded["workspace"]["workspace_id"]),
            account_id=UUID(seeded["xiaohongshu"]["id"]),
            content_id=UUID(seeded["xiaohongshu_content"]["id"]),
            platform="xiaohongshu",
            node=RiskScanNode.BEFORE_PUBLICATION,
            status=RiskScanStatus.FAILED,
            idempotency_key="agent-permission-failure-scan",
            input_fingerprint="c" * 64,
            input_snapshot={"synthetic": True},
            rule_version="rules-v1",
            evidence_version="evidence-v1",
            embedding_model_id="mock-embedding",
            embedding_version="embedding-v1",
            embedding_dimension=3,
            rag_model_version="mock-rag-v1",
            scanner_version="scanner-v1",
            result=None,
            error_code="PERMISSION_DENIED",
            diagnostics=[],
        )
    )
    session.commit()


def test_briefing_returns_one_highest_priority_candidate_without_cross_platform_score() -> None:
    with _seeded_workbench() as (client, _, seeded):
        workspace_id = seeded["workspace"]["workspace_id"]

        response = client.get(
            f"/v1/workspaces/{workspace_id}/agent/briefing"
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["primary"]["kind"] == "high_risk_blocked"
        assert payload["primary"]["platform"] == "douyin"
        assert (
            sum(item["is_primary"] for item in payload["candidates"]) == 1
        )
        assert "combined_score" not in response.text
        assert "PRIVATE_" not in response.text
        assert {
            item["platform"] for item in payload["candidates"]
        } <= {"douyin", "xiaohongshu"}


def test_briefing_reuses_same_record_until_confirmed_input_changes() -> None:
    with configured_client() as (client, _):
        workspace_id, csrf, account = create_workspace_account(client)

        first = client.get(
            f"/v1/workspaces/{workspace_id}/agent/briefing"
        )
        second = client.get(
            f"/v1/workspaces/{workspace_id}/agent/briefing"
        )
        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert first.json()["id"] == second.json()["id"]
        assert (
            first.json()["input_fingerprint"]
            == second.json()["input_fingerprint"]
        )

        create_published_content(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
            title="合成待分析内容",
            work_url="https://example.invalid/synthetic",
        )
        changed = client.get(
            f"/v1/workspaces/{workspace_id}/agent/briefing"
        )

        assert changed.status_code == 200, changed.text
        assert changed.json()["id"] != first.json()["id"]
        assert (
            changed.json()["input_fingerprint"]
            != first.json()["input_fingerprint"]
        )


def test_model_configuration_revision_invalidates_cached_briefing() -> None:
    with configured_client() as (client, engine):
        workspace_id, _, _ = create_workspace_account(client)
        first = client.get(
            f"/v1/workspaces/{workspace_id}/agent/briefing"
        ).json()

        with Session(engine) as session:
            session.add(
                ModelConfig(
                    workspace_id=UUID(workspace_id),
                    provider="synthetic-provider",
                    model_id="synthetic-text-model",
                    capabilities=["text"],
                    status=ModelConfigStatus.EXPERIMENTAL,
                    encrypted_api_key="synthetic-ciphertext",
                    configuration_revision=1,
                )
            )
            session.commit()

        changed = client.get(
            f"/v1/workspaces/{workspace_id}/agent/briefing"
        )

        assert changed.status_code == 200, changed.text
        assert changed.json()["id"] != first["id"]
        assert (
            changed.json()["input_fingerprint"]
            != first["input_fingerprint"]
        )


def test_failed_task_candidate_keeps_its_real_account_in_multi_account_workspace() -> None:
    with _seeded_workbench() as (client, _, seeded):
        workspace_id = seeded["workspace"]["workspace_id"]

        response = client.get(
            f"/v1/workspaces/{workspace_id}/agent/briefing"
        )

        assert response.status_code == 200, response.text
        failed_tasks = [
            item
            for item in response.json()["candidates"]
            if item["kind"] == "failed_task"
        ]
        assert len(failed_tasks) == 1
        assert failed_tasks[0]["platform"] == "xiaohongshu"
        assert (
            failed_tasks[0]["account_id"]
            == seeded["xiaohongshu"]["id"]
        )


def test_pending_import_invalidates_cache_and_becomes_account_scoped_candidate() -> None:
    with configured_client() as (client, _):
        workspace_id, csrf, account = create_workspace_account(client)
        first = client.get(
            f"/v1/workspaces/{workspace_id}/agent/briefing"
        ).json()

        preview = preview_manual(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account_id=account["id"],
            rows=[
                {
                    "platform_content_id": "synthetic-import-1",
                    "title": "合成待确认导入",
                    "body": "仅用于自动化测试",
                    "published_at": "2026-08-01T10:00:00+08:00",
                    "collected_at": "2026-08-02T10:00:00+08:00",
                    "metrics": {"views": 100},
                }
            ],
        )
        second = client.get(
            f"/v1/workspaces/{workspace_id}/agent/briefing"
        )

        assert second.status_code == 200, second.text
        payload = second.json()
        assert payload["id"] != first["id"]
        assert payload["primary"]["kind"] == "import_waiting_confirmation"
        assert payload["primary"]["account_id"] == account["id"]
        assert f"import_batch:{preview['id']}" in payload["primary"][
            "evidence_refs"
        ]


def test_permission_failure_is_classified_separately_from_suppressible_failures() -> None:
    with _seeded_workbench() as (client, engine, seeded):
        with Session(engine) as session:
            _add_permission_failure_scan(session, seeded=seeded)
        workspace_id = seeded["workspace"]["workspace_id"]

        response = client.get(
            f"/v1/workspaces/{workspace_id}/agent/briefing"
        )

        assert response.status_code == 200, response.text
        permission_failures = [
            item
            for item in response.json()["candidates"]
            if item["kind"] == "permission_security_failure"
        ]
        assert len(permission_failures) == 1
        assert (
            permission_failures[0]["account_id"]
            == seeded["xiaohongshu"]["id"]
        )


def test_permission_failure_candidate_cannot_be_suppressed() -> None:
    with _seeded_workbench() as (_, engine, seeded):
        workspace_id = UUID(seeded["workspace"]["workspace_id"])
        with Session(engine, expire_on_commit=False) as session:
            _add_permission_failure_scan(session, seeded=seeded)
            admin = next(
                member
                for member in session.query(WorkspaceMember).filter_by(
                    workspace_id=workspace_id,
                    role="admin",
                )
            )
            service = BriefingService(
                session,
                WorkspaceContext(
                    workspace_id=workspace_id,
                    member_id=admin.id,
                    role="admin",
                ),
            )
            briefing = service.generate()
            permission_candidate = next(
                item
                for item in briefing.candidates
                if item.kind == "permission_security_failure"
            )

            with pytest.raises(ValueError, match="cannot be suppressed"):
                service.record_decision(
                    briefing.id,
                    decision="suppress_kind",
                    candidate_kind=permission_candidate.kind,
                    idempotency_key="forbidden-permission-suppression",
                )


def test_defer_and_suppress_change_future_candidate_selection() -> None:
    with configured_client() as (client, _):
        workspace_id, csrf, account = create_workspace_account(client)
        create_published_content(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
            title="合成待分析内容",
            work_url="https://example.invalid/synthetic",
        )
        briefing = client.get(
            f"/v1/workspaces/{workspace_id}/agent/briefing"
        ).json()
        assert briefing["primary"]["kind"] == "preflight_review_required"

        deferred = client.post(
            (
                f"/v1/workspaces/{workspace_id}/agent/briefings/"
                f"{briefing['id']}/decisions"
            ),
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "defer-pending-analysis",
            },
            json={"decision": "defer", "candidate_kind": None},
        )
        assert deferred.status_code == 200, deferred.text
        assert (
            deferred.json()["primary"]["kind"]
            != "preflight_review_required"
        )

        deferred_payload = deferred.json()
        suppressed_kind = deferred_payload["primary"]["kind"]
        suppressed = client.post(
            (
                f"/v1/workspaces/{workspace_id}/agent/briefings/"
                f"{deferred_payload['id']}/decisions"
            ),
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "suppress-current-kind",
            },
            json={
                "decision": "suppress_kind",
                "candidate_kind": suppressed_kind,
            },
        )

        assert suppressed.status_code == 200, suppressed.text
        assert suppressed_kind not in {
            item["kind"] for item in suppressed.json()["candidates"]
        }


def test_high_risk_candidate_cannot_be_suppressed() -> None:
    with _seeded_workbench() as (client, engine, seeded):
        workspace_id = seeded["workspace"]["workspace_id"]
        with Session(engine, expire_on_commit=False) as session:
            admin = next(
                member
                for member in session.query(WorkspaceMember).filter_by(
                    workspace_id=UUID(workspace_id),
                    role="admin",
                )
            )
            service = BriefingService(
                session,
                WorkspaceContext(
                    workspace_id=admin.workspace_id,
                    member_id=admin.id,
                    role="admin",
                ),
            )
            briefing = service.generate()
            assert briefing.primary is not None
            assert briefing.primary.kind == "high_risk_blocked"

            with pytest.raises(
                ValueError,
                match="cannot be suppressed",
            ):
                service.record_decision(
                    briefing.id,
                    decision="suppress_kind",
                    candidate_kind=briefing.primary.kind,
                    idempotency_key="forbidden-risk-suppression",
                )


def test_viewer_cannot_refresh_and_cross_workspace_stays_hidden() -> None:
    with _seeded_workbench() as (client, _, seeded):
        workspace_id = seeded["workspace"]["workspace_id"]
        foreign_workspace_id = seeded["foreign"]["workspace_id"]

        refresh = client.post(
            f"/v1/workspaces/{workspace_id}/agent/briefing/refresh",
            headers={
                "X-CSRF-Token": seeded["viewer_login"]["csrf_token"],
                "Idempotency-Key": "viewer-refresh",
            },
        )
        foreign = client.get(
            f"/v1/workspaces/{foreign_workspace_id}/agent/briefing"
        )

        assert refresh.status_code == 403
        assert foreign.status_code == 404


def test_refresh_is_idempotent_without_duplicate_events() -> None:
    with configured_client() as (client, engine):
        workspace_id, csrf, _ = create_workspace_account(client)
        headers = {
            "X-CSRF-Token": csrf,
            "Idempotency-Key": "repeat-agent-refresh",
        }

        first = client.post(
            f"/v1/workspaces/{workspace_id}/agent/briefing/refresh",
            headers=headers,
        )
        repeated = client.post(
            f"/v1/workspaces/{workspace_id}/agent/briefing/refresh",
            headers=headers,
        )

        assert first.status_code == 200, first.text
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["id"] == first.json()["id"]
        with Session(engine) as session:
            events = session.query(AgentEvent).filter_by(
                workspace_id=UUID(workspace_id),
                event_type="briefing_refresh_requested",
            )
            assert events.count() == 1


def test_decision_contract_rejects_unknown_fields() -> None:
    with configured_client() as (client, _):
        workspace_id, csrf, _ = create_workspace_account(client)
        briefing = client.get(
            f"/v1/workspaces/{workspace_id}/agent/briefing"
        ).json()

        response = client.post(
            (
                f"/v1/workspaces/{workspace_id}/agent/briefings/"
                f"{briefing['id']}/decisions"
            ),
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "unknown-decision-field",
            },
            json={
                "decision": "defer",
                "candidate_kind": None,
                "prompt": "must be rejected",
            },
        )

        assert response.status_code == 422
