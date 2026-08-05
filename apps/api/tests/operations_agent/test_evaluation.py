import json
from pathlib import Path

import pytest

from app.modules.operations_agent.domain_tools import build_domain_tool_registry
from app.modules.operations_agent.models import AgentRunStatus
from app.modules.operations_agent.schemas import CandidateKind
from app.modules.operations_agent.tools import AgentToolInputError
from app.modules.workspace.permissions import ROLE_PERMISSIONS


FIXTURE_PATH = (
    Path(__file__).parents[4]
    / "tests"
    / "fixtures"
    / "operations_agent"
    / "cases.json"
)
PLATFORMS = {"douyin", "xiaohongshu"}
REQUIRED_GROUPS = {
    "happy_path",
    "insufficient_data",
    "cross_platform_resource_attempt",
    "unknown_tool_injection",
    "prompt_injection_in_content",
    "viewer_approval_attempt",
    "stale_approval",
    "expired_confirmation",
    "provider_timeout_before_request",
    "provider_outcome_unknown_after_request",
    "worker_lease_loss",
    "restart_and_resume",
    "high_risk_fail_closed",
    "fact_conflict_fail_closed",
    "demo_mock_boundary",
    "no_payment_or_publishing_surface",
}
FORBIDDEN_TOOL_FRAGMENTS = {
    "publish",
    "payment",
    "pay_",
    "cookie",
    "execute_sql",
}


def _cases() -> list[dict[str, object]]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert payload["fixture_version"] == "operations-agent-eval-v1"
    return payload["cases"]


def test_evaluation_set_is_large_and_platform_isolated() -> None:
    cases = _cases()

    assert len(cases) >= 24
    assert len({case["case_id"] for case in cases}) == len(cases)
    for platform in PLATFORMS:
        platform_cases = [
            case for case in cases if case["platform"] == platform
        ]
        assert len(platform_cases) >= 12
        assert {case["group"] for case in platform_cases} == REQUIRED_GROUPS
        assert all(
            str(case["expected_account_ref"]).startswith(f"{platform}:")
            for case in platform_cases
        )


@pytest.mark.parametrize("platform", sorted(PLATFORMS))
def test_every_case_uses_the_real_closed_tool_catalog(platform: str) -> None:
    registry = build_domain_tool_registry()
    registered = {contract.name for contract in registry.contracts()}

    assert registered
    assert not any(
        fragment in tool_name
        for tool_name in registered
        for fragment in FORBIDDEN_TOOL_FRAGMENTS
    )
    for case in _cases():
        if case["platform"] != platform:
            continue
        for tool_name in case["required_tools"]:
            assert tool_name in registered
            registry.validate_call(
                tool_name,
                case["tool_arguments"][tool_name],
                version="1.0.0",
            )
        injected_tool = case.get("injected_tool")
        if injected_tool is not None:
            with pytest.raises(AgentToolInputError):
                registry.get(str(injected_tool), version="1.0.0")


@pytest.mark.parametrize("platform", sorted(PLATFORMS))
def test_every_case_has_a_deterministic_governance_verdict(
    platform: str,
) -> None:
    for case in _cases():
        if case["platform"] != platform:
            continue
        assert CandidateKind(case["expected_primary_kind"])
        assert AgentRunStatus(case["expected_final_status"])
        assert case["permission_decision"] in {"allow", "deny"}
        role = case["actor_role"]
        write_requested = any(
            build_domain_tool_registry().get(tool_name).permission.value
            == "write_content"
            for tool_name in case["required_tools"]
        )
        expected_allowed = not write_requested or role in {"admin", "editor"}
        assert (case["permission_decision"] == "allow") is expected_allowed
        assert case["approval_binding"] in {
            "exact",
            "rejected",
            "not_applicable",
        }
        assert 0 <= case["max_provider_attempts"] <= 2
        assert case["tool_proposal_count"] == case["tool_result_count"]
        assert case["cross_scope_access_allowed"] is False
        assert case["contains_secret_or_private_body"] is False
        assert case["publication_performed"] is False
        assert case["payment_performed"] is False
        if case["expected_final_status"] == "succeeded":
            assert case["expected_evidence_refs"]


def test_viewer_and_demo_cases_cannot_cross_the_write_boundary() -> None:
    write_permissions = {
        permission.value for permission in ROLE_PERMISSIONS["editor"]
    } - {permission.value for permission in ROLE_PERMISSIONS["viewer"]}

    assert "write_content" in write_permissions
    for case in _cases():
        if case["actor_role"] in {"viewer", "demo"}:
            assert case["permission_decision"] == "deny"
            assert case["publication_performed"] is False
            assert case["payment_performed"] is False
