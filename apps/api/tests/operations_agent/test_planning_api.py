import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from app.core.security import WorkspaceContext
from app.modules.content.account_models import PlatformAccount
from app.modules.operations_agent.planning import (
    AgentApprovalStale,
    InvalidAgentPlan,
    PlanService,
    PlanValidator,
    build_planning_registry,
)
from app.modules.operations_agent.models import AgentEvent, AgentRun
from app.modules.operations_agent.schemas import (
    AllowedToolSummary,
    PlannerRequest,
)
from app.modules.workspace.models import WorkspaceMember
from app.modules.workspace.permissions import PermissionDenied
from tests.imports.helpers import (
    configured_client,
    create_published_content,
    create_workspace_account,
)


def _planner_request(account_id: UUID) -> PlannerRequest:
    return PlannerRequest(
        objective="检查账号当前最需要处理的问题",
        briefing_id=uuid4(),
        platform="douyin",
        account_id=account_id,
        candidate_id="candidate-1",
        briefing_input_fingerprint="a" * 64,
        allowed_tools=(
            AllowedToolSummary(
                name="read_account_state",
                version="1.0.0",
                risk="read_only",
                prerequisites=(),
            ),
        ),
        evidence_refs=(f"account:{account_id}",),
    )


def _plan_payload(request: PlannerRequest, *, tool_name: str) -> dict:
    return {
        "goal": request.objective,
        "platform": request.platform,
        "account_id": str(request.account_id),
        "candidate_id": request.candidate_id,
        "input_fingerprint": request.briefing_input_fingerprint,
        "tool_catalog_version": "operations-agent-tools-v1",
        "steps": [
            {
                "step_index": 0,
                "tool_name": tool_name,
                "tool_version": "1.0.0",
                "arguments": {"account_id": str(request.account_id)},
                "rationale": "读取账号的安全状态摘要",
            }
        ],
    }


def _create_plan(
    client,
    *,
    workspace_id: str,
    csrf: str,
    account: dict,
) -> dict:
    briefing = client.get(
        f"/v1/workspaces/{workspace_id}/agent/briefing"
    )
    assert briefing.status_code == 200, briefing.text
    response = client.post(
        f"/v1/workspaces/{workspace_id}/agent/plans",
        headers={
            "X-CSRF-Token": csrf,
            "Idempotency-Key": "create-synthetic-plan",
        },
        json={
            "objective": "找出这个账号当前最值得先处理的问题",
            "briefing_id": briefing.json()["id"],
            "platform": account["platform"],
            "account_id": account["id"],
            "planner": "deterministic",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_planner_cannot_add_unknown_tool() -> None:
    request = _planner_request(uuid4())
    validator = PlanValidator(build_planning_registry())

    with pytest.raises(InvalidAgentPlan, match="unknown agent tool"):
        validator.validate(
            model_output=_plan_payload(
                request,
                tool_name="publish_to_xiaohongshu",
            ),
            request=request,
        )


@pytest.mark.parametrize(
    "model_output",
    (
        "```json\n{}\n```",
        "{} 额外解释",
    ),
)
def test_planner_rejects_markdown_and_extra_prose(
    model_output: str,
) -> None:
    request = _planner_request(uuid4())
    validator = PlanValidator(build_planning_registry())

    with pytest.raises(InvalidAgentPlan):
        validator.validate(model_output=model_output, request=request)


def test_planner_rejects_cross_account_and_arbitrary_url_arguments() -> None:
    request = _planner_request(uuid4())
    validator = PlanValidator(build_planning_registry())
    cross_account = _plan_payload(
        request,
        tool_name="read_account_state",
    )
    cross_account["steps"][0]["arguments"]["account_id"] = str(uuid4())
    arbitrary_url = _plan_payload(
        request,
        tool_name="read_account_state",
    )
    arbitrary_url["steps"][0]["arguments"]["url"] = (
        "https://example.invalid/private"
    )

    with pytest.raises(InvalidAgentPlan, match="account scope"):
        validator.validate(model_output=cross_account, request=request)
    with pytest.raises(InvalidAgentPlan, match="invalid arguments"):
        validator.validate(model_output=arbitrary_url, request=request)


def test_planner_rejects_duplicate_json_keys() -> None:
    request = _planner_request(uuid4())
    validator = PlanValidator(build_planning_registry())
    encoded = json.dumps(
        _plan_payload(request, tool_name="read_account_state"),
        ensure_ascii=False,
    )
    duplicate_goal = encoded.replace(
        f'"goal": "{request.objective}"',
        f'"goal": "被覆盖的目标", "goal": "{request.objective}"',
        1,
    )

    with pytest.raises(InvalidAgentPlan, match="duplicate"):
        validator.validate(model_output=duplicate_goal, request=request)


def test_plan_approval_is_invalidated_by_account_version_change() -> None:
    with configured_client() as (client, engine):
        workspace_id, csrf, account = create_workspace_account(client)
        plan = _create_plan(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
        )
        approved = client.post(
            (
                f"/v1/workspaces/{workspace_id}/agent/plans/"
                f"{plan['id']}/approve"
            ),
            headers={"X-CSRF-Token": csrf},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"

        with Session(engine, expire_on_commit=False) as session:
            stored_account = session.get(
                PlatformAccount,
                UUID(account["id"]),
            )
            assert stored_account is not None
            stored_account.name = "已更新的合成账号配置"
            session.commit()
            admin = session.query(WorkspaceMember).filter_by(
                workspace_id=UUID(workspace_id),
                role="admin",
            ).one()
            service = PlanService(
                session,
                WorkspaceContext(
                    workspace_id=UUID(workspace_id),
                    member_id=admin.id,
                    role="admin",
                ),
            )

            with pytest.raises(AgentApprovalStale):
                service.assert_approval_current(UUID(plan["id"]))


def test_plan_approval_is_invalidated_by_new_briefing_input() -> None:
    with configured_client() as (client, engine):
        workspace_id, csrf, account = create_workspace_account(client)
        plan = _create_plan(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
        )
        approved = client.post(
            (
                f"/v1/workspaces/{workspace_id}/agent/plans/"
                f"{plan['id']}/approve"
            ),
            headers={"X-CSRF-Token": csrf},
        )
        assert approved.status_code == 200, approved.text
        create_published_content(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
            title="批准后新增的合成内容",
            work_url="https://example.invalid/synthetic-plan-stale",
        )

        with Session(engine, expire_on_commit=False) as session:
            admin = session.query(WorkspaceMember).filter_by(
                workspace_id=UUID(workspace_id),
                role="admin",
            ).one()
            service = PlanService(
                session,
                WorkspaceContext(
                    workspace_id=UUID(workspace_id),
                    member_id=admin.id,
                    role="admin",
                ),
            )

            with pytest.raises(AgentApprovalStale):
                service.assert_approval_current(UUID(plan["id"]))


def test_viewer_cannot_approve_plan() -> None:
    with configured_client() as (client, _):
        workspace_id, csrf, account = create_workspace_account(client)
        plan = _create_plan(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
        )
        invite = client.post(
            f"/v1/workspaces/{workspace_id}/members/codes",
            headers={"X-CSRF-Token": csrf},
            json={"role": "viewer"},
        )
        assert invite.status_code == 201, invite.text
        viewer_login = client.post(
            "/v1/sessions/invite",
            json={
                "code": invite.json()["code"],
                "display_name": "计划只读用户",
            },
        )
        assert viewer_login.status_code == 201, viewer_login.text

        response = client.post(
            (
                f"/v1/workspaces/{workspace_id}/agent/plans/"
                f"{plan['id']}/approve"
            ),
            headers={
                "X-CSRF-Token": viewer_login.json()["csrf_token"],
            },
        )

        assert response.status_code == 403


def test_plan_service_rejects_direct_viewer_approval() -> None:
    with configured_client() as (client, engine):
        workspace_id, csrf, account = create_workspace_account(client)
        plan = _create_plan(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
        )
        invite = client.post(
            f"/v1/workspaces/{workspace_id}/members/codes",
            headers={"X-CSRF-Token": csrf},
            json={"role": "viewer"},
        )
        viewer_login = client.post(
            "/v1/sessions/invite",
            json={
                "code": invite.json()["code"],
                "display_name": "直接服务只读用户",
            },
        ).json()

        with Session(engine, expire_on_commit=False) as session:
            service = PlanService(
                session,
                WorkspaceContext(
                    workspace_id=UUID(workspace_id),
                    member_id=UUID(viewer_login["member_id"]),
                    role="viewer",
                ),
            )

            with pytest.raises(PermissionDenied):
                service.approve(UUID(plan["id"]))


def test_plan_creation_is_idempotent_and_conflicting_reuse_is_rejected() -> None:
    with configured_client() as (client, _):
        workspace_id, csrf, account = create_workspace_account(client)
        first = _create_plan(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
        )
        repeated = _create_plan(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
        )
        briefing = client.get(
            f"/v1/workspaces/{workspace_id}/agent/briefing"
        ).json()
        conflict = client.post(
            f"/v1/workspaces/{workspace_id}/agent/plans",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "create-synthetic-plan",
            },
            json={
                "objective": "不同的目标不能复用同一个幂等键",
                "briefing_id": briefing["id"],
                "platform": account["platform"],
                "account_id": account["id"],
                "planner": "deterministic",
            },
        )

        assert repeated["id"] == first["id"]
        assert conflict.status_code == 409


def test_approved_plan_can_start_one_durable_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enqueued: list[str] = []
    with configured_client() as (client, engine):
        from app.modules.operations_agent import router as agent_router

        monkeypatch.setattr(
            agent_router,
            "_enqueue_run",
            lambda run_id: enqueued.append(run_id),
        )
        workspace_id, csrf, account = create_workspace_account(client)
        plan = _create_plan(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
        )
        approved = client.post(
            (
                f"/v1/workspaces/{workspace_id}/agent/plans/"
                f"{plan['id']}/approve"
            ),
            headers={"X-CSRF-Token": csrf},
        )
        assert approved.status_code == 200, approved.text

        path = (
            f"/v1/workspaces/{workspace_id}/agent/plans/"
            f"{plan['id']}/runs"
        )
        first = client.post(path, headers={"X-CSRF-Token": csrf})
        repeated = client.post(path, headers={"X-CSRF-Token": csrf})

        assert first.status_code == 201, first.text
        assert repeated.status_code == 201, repeated.text
        assert repeated.json()["id"] == first.json()["id"]
        assert repeated.json()["status"] == "queued"
        with Session(engine) as session:
            assert (
                session.query(AgentRun)
                .filter_by(
                    workspace_id=UUID(workspace_id),
                    plan_id=UUID(plan["id"]),
                )
                .count()
                == 1
            )
        assert enqueued == [UUID(first.json()["id"])]


def test_rejection_is_terminal_idempotent_and_append_only() -> None:
    with configured_client() as (client, engine):
        workspace_id, csrf, account = create_workspace_account(client)
        plan = _create_plan(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
        )
        path = (
            f"/v1/workspaces/{workspace_id}/agent/plans/"
            f"{plan['id']}/reject"
        )

        rejected = client.post(path, headers={"X-CSRF-Token": csrf})
        repeated = client.post(path, headers={"X-CSRF-Token": csrf})
        approve_after_rejection = client.post(
            path.removesuffix("/reject") + "/approve",
            headers={"X-CSRF-Token": csrf},
        )

        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["status"] == "rejected"
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["id"] == rejected.json()["id"]
        assert approve_after_rejection.status_code == 409
        with Session(engine) as session:
            assert (
                session.query(AgentEvent)
                .filter_by(
                    workspace_id=UUID(workspace_id),
                    event_type="plan_rejected",
                )
                .count()
                == 1
            )


def test_cross_workspace_plan_read_returns_not_found() -> None:
    with configured_client() as (client, _):
        workspace_id, csrf, account = create_workspace_account(client)
        plan = _create_plan(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
        )
        foreign_workspace = client.post(
            "/v1/workspaces",
            json={"name": "其他合成团队"},
        ).json()
        foreign_login = client.post(
            "/v1/sessions/invite",
            json={
                "code": foreign_workspace["admin_code"],
                "display_name": "其他团队管理员",
            },
        )
        assert foreign_login.status_code == 201, foreign_login.text

        response = client.get(
            (
                f"/v1/workspaces/{foreign_workspace['workspace_id']}/"
                f"agent/plans/{plan['id']}"
            )
        )

        assert response.status_code == 404
