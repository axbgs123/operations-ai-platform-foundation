from collections.abc import Mapping, Sequence
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.modules.exports.deletion import PRIVATE_WORKSPACE_TABLES
from app.modules.exports.json_backup import build_lightweight_manifest
from app.modules.exports.restore_preview import (
    RestoreMode,
    apply_lightweight_restore,
    build_restore_preview,
)
from app.modules.operations_agent.executor import AgentConfirmationStale
from app.modules.operations_agent.models import (
    AgentArtifact,
    AgentArtifactKind,
    AgentBriefing,
    AgentConfirmation,
    AgentConfirmationStatus,
    AgentEvent,
    AgentPlan,
    AgentPlanStatus,
    AgentRun,
    AgentRunStep,
    AgentRunStatus,
    AgentStepStatus,
    AgentToolRisk,
)
from tests.operations_agent.test_executor import _executor_fixture


def _recursive_keys(value: object) -> set[str]:
    if isinstance(value, Mapping):
        return {
            str(key)
            for key in value
        } | {
            nested
            for item in value.values()
            for nested in _recursive_keys(item)
        }
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return {
            nested for item in value for nested in _recursive_keys(item)
        }
    return set()


def _pending_confirmation(fixture):
    claim = fixture.executor.claim_next_step(fixture.run_id)
    fixture.executor.execute_claim(claim)
    with fixture.factory() as session:
        confirmation = session.scalar(
            select(AgentConfirmation).where(
                AgentConfirmation.run_id == fixture.run_id
            )
        )
        assert confirmation is not None
        return confirmation


def test_confirmation_cannot_authorize_changed_arguments() -> None:
    with _executor_fixture(risk=AgentToolRisk.PROTECTED_WRITE) as fixture:
        confirmation = _pending_confirmation(fixture)
        with fixture.factory.begin() as session:
            step = session.get(AgentRunStep, confirmation.step_id)
            assert step is not None
            step.input_envelope = {
                **step.input_envelope,
                "arguments": {"account_id": str(uuid4())},
            }

        with pytest.raises(AgentConfirmationStale):
            fixture.executor.decide_confirmation(
                fixture.run_id,
                confirmation_id=confirmation.id,
                decision="approve",
                action_fingerprint=confirmation.action_fingerprint,
                context=fixture.context,
            )


def test_confirmation_is_single_use_and_requeues_exact_step() -> None:
    with _executor_fixture(risk=AgentToolRisk.PROTECTED_WRITE) as fixture:
        confirmation = _pending_confirmation(fixture)

        approved = fixture.executor.decide_confirmation(
            fixture.run_id,
            confirmation_id=confirmation.id,
            decision="approve",
            action_fingerprint=confirmation.action_fingerprint,
            context=fixture.context,
        )

        assert approved.status is AgentConfirmationStatus.APPROVED
        claim = fixture.executor.claim_next_step(fixture.run_id)
        result = fixture.executor.execute_claim(claim)
        assert result.run_status.value == "succeeded"
        assert len(fixture.runner.calls) == 1
        with pytest.raises(ValueError, match="already resolved"):
            fixture.executor.decide_confirmation(
                fixture.run_id,
                confirmation_id=confirmation.id,
                decision="approve",
                action_fingerprint=confirmation.action_fingerprint,
                context=fixture.context,
            )


def test_confirmation_is_invalidated_when_plan_is_no_longer_approved() -> None:
    with _executor_fixture(risk=AgentToolRisk.PROTECTED_WRITE) as fixture:
        confirmation = _pending_confirmation(fixture)
        with fixture.factory.begin() as session:
            run = session.get(AgentRun, fixture.run_id)
            assert run is not None
            plan = session.get(AgentPlan, run.plan_id)
            assert plan is not None
            plan.status = AgentPlanStatus.INVALIDATED

        with pytest.raises(AgentConfirmationStale):
            fixture.executor.decide_confirmation(
                fixture.run_id,
                confirmation_id=confirmation.id,
                decision="approve",
                action_fingerprint=confirmation.action_fingerprint,
                context=fixture.context,
            )

        with fixture.factory() as session:
            stored = session.get(AgentConfirmation, confirmation.id)
            assert stored is not None
            assert stored.status is AgentConfirmationStatus.INVALIDATED


def test_confirmation_inbox_and_run_usage_have_no_product_billing_fields() -> None:
    with _executor_fixture(risk=AgentToolRisk.PROTECTED_WRITE) as fixture:
        confirmation = _pending_confirmation(fixture)
        workspace_id = str(fixture.context.workspace_id)

        inbox = fixture.client.get(
            f"/v1/workspaces/{workspace_id}/agent/confirmations"
        )
        run = fixture.client.get(
            f"/v1/workspaces/{workspace_id}/agent/runs/{fixture.run_id}"
        )

        assert inbox.status_code == 200, inbox.text
        assert [item["id"] for item in inbox.json()["items"]] == [
            str(confirmation.id)
        ]
        assert run.status_code == 200, run.text
        assert {
            "uses_external_api",
            "provider",
            "model_id",
            "attempt_count",
            "input_tokens",
            "output_tokens",
            "embedding_tokens",
            "ocr_images",
            "generated_images",
            "usage_status",
        }.issubset(run.json()["usage"])
        forbidden = {
            "payment",
            "balance",
            "credits",
            "subscription",
            "recharge",
            "api_key",
            "provider_workspace_id",
        }
        assert not forbidden.intersection(
            _recursive_keys([inbox.json(), run.json()])
        )


def test_confirmation_inbox_only_returns_current_members_actions() -> None:
    with _executor_fixture(risk=AgentToolRisk.PROTECTED_WRITE) as fixture:
        _pending_confirmation(fixture)
        workspace_id = str(fixture.context.workspace_id)
        invite = fixture.client.post(
            f"/v1/workspaces/{workspace_id}/members/codes",
            headers={"X-CSRF-Token": fixture.csrf},
            json={"role": "viewer"},
        )
        assert invite.status_code == 201, invite.text
        viewer = TestClient(app)
        login = viewer.post(
            "/v1/sessions/invite",
            json={
                "code": invite.json()["code"],
                "display_name": "其他只读成员",
            },
        )
        assert login.status_code == 201, login.text

        inbox = viewer.get(
            f"/v1/workspaces/{workspace_id}/agent/confirmations"
        )

        assert inbox.status_code == 200, inbox.text
        assert inbox.json()["items"] == []
        viewer.close()


def test_lightweight_backup_contains_only_safe_agent_metadata() -> None:
    with _executor_fixture() as fixture:
        claim = fixture.executor.claim_next_step(fixture.run_id)
        fixture.executor.execute_claim(claim)
        with fixture.factory.begin() as session:
            step = session.scalar(
                select(AgentRunStep).where(
                    AgentRunStep.run_id == fixture.run_id
                )
            )
            assert step is not None
            session.add(
                AgentArtifact(
                    workspace_id=fixture.context.workspace_id,
                    run_id=fixture.run_id,
                    kind=AgentArtifactKind.EXECUTION_SUMMARY,
                    resource_type="execution_summary",
                    resource_id=uuid4(),
                    step_id=step.id,
                    safe_metadata={
                        "publication_performed": False,
                        "prompt": "MUST_NOT_EXPORT",
                    },
                )
            )
        with fixture.factory() as session:
            manifest = build_lightweight_manifest(
                session,
                fixture.context,
            )

        agent_records = [
            item
            for item in manifest.records
            if item.record_type.value.startswith("agent_")
        ]
        assert {
            "agent_briefing",
            "agent_plan",
            "agent_run",
            "agent_step",
            "agent_artifact",
            "agent_event",
        }.issubset({item.record_type.value for item in agent_records})
        assert not {
            "prompt",
            "title",
            "body",
            "model_output",
            "tool_arguments",
            "confirmation_token",
            "action_fingerprint",
            "claim_token",
            "lease_expires_at",
        }.intersection(
            _recursive_keys([item.model_dump() for item in agent_records])
        )
        assert not any(
            item.record_type.value == "agent_confirmation"
            for item in manifest.records
        )


def test_lightweight_restore_imports_agent_history_as_terminal_read_only() -> None:
    with _executor_fixture() as fixture:
        claim = fixture.executor.claim_next_step(fixture.run_id)
        fixture.executor.execute_claim(claim)
        with fixture.factory() as session:
            manifest = build_lightweight_manifest(session, fixture.context)
            preview = build_restore_preview(
                session,
                fixture.context,
                manifest,
                mode=RestoreMode.NEW,
                idempotency_key="restore-agent-history",
            )
            apply_lightweight_restore(
                session,
                fixture.context,
                manifest,
                preview,
            )
            session.commit()
            target_workspace_id = preview.target_workspace_id
            assert target_workspace_id is not None

        with fixture.factory() as session:
            restored_plan = session.scalar(
                select(AgentPlan).where(
                    AgentPlan.workspace_id == target_workspace_id
                )
            )
            restored_run = session.scalar(
                select(AgentRun).where(
                    AgentRun.workspace_id == target_workspace_id
                )
            )
            restored_step = session.scalar(
                select(AgentRunStep).where(
                    AgentRunStep.workspace_id == target_workspace_id
                )
            )
            assert restored_plan is not None
            assert restored_plan.status is AgentPlanStatus.INVALIDATED
            assert restored_run is not None
            assert restored_run.status is AgentRunStatus.CANCELLED
            assert restored_step is not None
            assert restored_step.status is AgentStepStatus.CANCELLED
            assert (
                session.query(AgentConfirmation)
                .filter_by(workspace_id=target_workspace_id)
                .count()
                == 0
            )


def test_workspace_deletion_inventory_covers_every_agent_table() -> None:
    assert {
        AgentBriefing.__tablename__,
        AgentPlan.__tablename__,
        AgentRun.__tablename__,
        AgentRunStep.__tablename__,
        AgentConfirmation.__tablename__,
        AgentArtifact.__tablename__,
        AgentEvent.__tablename__,
    }.issubset(PRIVATE_WORKSPACE_TABLES)
