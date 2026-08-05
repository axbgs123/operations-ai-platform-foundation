from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.security import WorkspaceContext
from app.modules.models.models import ModelConfig, ModelConfigStatus
from app.modules.exports.report import render_agent_execution_markdown
from app.modules.operations_agent.domain_tools import (
    DomainToolRunner,
    build_domain_tool_registry,
)
from app.modules.operations_agent.executor import AgentExecutor, ToolInvocation
from app.modules.operations_agent.models import (
    AgentArtifact,
    AgentRunStatus,
)
from app.modules.workspace.models import WorkspaceMember
from tests.imports.helpers import (
    configured_client,
    create_published_content,
    create_workspace_account,
)


EXPECTED_TOOLS = {
    "read_account_state",
    "run_content_analysis",
    "read_confirmed_facts",
    "read_account_style",
    "read_confirmed_viral_assets",
    "generate_optimization_draft",
    "scan_optimization_draft",
    "save_agent_summary",
    "create_agent_export",
}


def test_domain_catalog_exposes_only_the_nine_governed_tools() -> None:
    registry = build_domain_tool_registry()

    assert registry.catalog_version == "operations-agent-tools-v1"
    assert {contract.name for contract in registry.contracts()} == EXPECTED_TOOLS


def test_domain_runner_rejects_cross_platform_account_before_tool_use() -> None:
    with configured_client() as (client, engine):
        workspace_id, _, account = create_workspace_account(
            client,
            platform="xiaohongshu",
        )
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        runner = DomainToolRunner(factory)
        with factory() as session:
            actor_id = session.query(WorkspaceMember.id).filter_by(
                workspace_id=UUID(workspace_id)
            ).scalar()
        assert actor_id is not None

        observation = runner.invoke(
            ToolInvocation(
                workspace_id=UUID(workspace_id),
                run_id=uuid4(),
                step_id=uuid4(),
                account_id=UUID(account["id"]),
                platform="douyin",
                actor_id=actor_id,
                tool_name="read_account_state",
                tool_version="1.0.0",
                arguments={"account_id": account["id"]},
            )
        )

    assert observation.status == "denied"
    assert observation.error_code == "AGENT_RESOURCE_SCOPE_MISMATCH"
    assert observation.artifact_refs == ()


def test_read_account_state_returns_only_a_safe_summary() -> None:
    with configured_client() as (client, engine):
        workspace_id, _, account = create_workspace_account(client)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        runner = DomainToolRunner(factory)
        with factory() as session:
            actor_id = session.query(WorkspaceMember.id).filter_by(
                workspace_id=UUID(workspace_id)
            ).scalar()
        assert actor_id is not None

        observation = runner.invoke(
            ToolInvocation(
                workspace_id=UUID(workspace_id),
                run_id=uuid4(),
                step_id=uuid4(),
                account_id=UUID(account["id"]),
                platform=account["platform"],
                actor_id=actor_id,
                tool_name="read_account_state",
                tool_version="1.0.0",
                arguments={"account_id": account["id"]},
            )
        )

    assert observation.status == "success"
    assert observation.artifact_refs == ()
    assert "账号" in observation.safe_summary
    assert "prompt" not in observation.safe_summary.lower()


def test_first_content_loop_succeeds_with_reviewable_artifacts_only() -> None:
    with configured_client() as (client, engine):
        workspace_id, csrf, account = create_workspace_account(client)
        content = create_published_content(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
            title="人工合成待优化内容",
            work_url="https://example.invalid/agent-loop",
        )
        snapshot = client.post(
            f"/v1/contents/{content['id']}/snapshots",
            headers={"X-CSRF-Token": csrf},
            json={
                "collected_at": datetime.fromisoformat(
                    content["published_at"]
                ).astimezone(UTC).isoformat(),
                "source": "manual",
                "metrics": [{"key": "views", "raw_value": 120}],
            },
        ).json()
        confirmed = client.post(
            f"/v1/contents/{content['id']}/snapshots/{snapshot['id']}/confirm",
            headers={"X-CSRF-Token": csrf},
        )
        assert confirmed.status_code == 200, confirmed.text
        with Session(engine) as session:
            member = session.scalar(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == UUID(workspace_id),
                    WorkspaceMember.role == "admin",
                )
            )
            assert member is not None
            session.add(
                ModelConfig(
                    workspace_id=UUID(workspace_id),
                    provider="mock",
                    model_id="mock-text-v1",
                    capabilities=["text"],
                    status=ModelConfigStatus.VERIFIED,
                    encrypted_api_key="synthetic-encrypted-placeholder",
                )
            )
            session.commit()
            actor_id = member.id
        briefing = client.get(
            f"/v1/workspaces/{workspace_id}/agent/briefing"
        )
        assert briefing.status_code == 200, briefing.text
        assert briefing.json()["primary"]["content_id"] == content["id"]
        plan = client.post(
            f"/v1/workspaces/{workspace_id}/agent/plans",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "first-domain-loop",
            },
            json={
                "objective": "分析并生成一份可人工复核的优化方案",
                "briefing_id": briefing.json()["id"],
                "platform": account["platform"],
                "account_id": account["id"],
                "planner": "deterministic",
            },
        )
        assert plan.status_code == 201, plan.text
        approved = client.post(
            (
                f"/v1/workspaces/{workspace_id}/agent/plans/"
                f"{plan.json()['id']}/approve"
            ),
            headers={"X-CSRF-Token": csrf},
        )
        assert approved.status_code == 200, approved.text
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        registry = build_domain_tool_registry()
        executor = AgentExecutor(
            factory,
            registry=registry,
            tool_runner=DomainToolRunner(factory, registry=registry),
        )
        run = executor.create_run(
            UUID(plan.json()["id"]),
            context=WorkspaceContext(
                workspace_id=UUID(workspace_id),
                member_id=actor_id,
                role="admin",
            ),
        )
        result = None
        for step_index in range(9):
            try:
                claim = executor.claim_next_step(run.id)
            except Exception as error:
                raise AssertionError(
                    f"step {step_index} could not be claimed"
                ) from error
            result = executor.execute_claim(claim)
        assert result is not None
        assert result.run_status is AgentRunStatus.SUCCEEDED
        with factory() as session:
            artifacts = list(
                session.scalars(
                    select(AgentArtifact).where(
                        AgentArtifact.run_id == run.id
                    )
                )
            )
            markdown = render_agent_execution_markdown(
                session,
                WorkspaceContext(
                    workspace_id=UUID(workspace_id),
                    member_id=actor_id,
                    role="admin",
                ),
                UUID(content["id"]),
                run.id,
            )
        assert {artifact.kind.value for artifact in artifacts} == {
            "analysis",
            "text_draft",
            "cover_recommendation",
            "risk_scan",
            "execution_summary",
            "export",
        }
        assert all(
            artifact.safe_metadata.get("publication_performed") is not True
            for artifact in artifacts
        )
        assert "# 运营智能体执行包" in markdown
        assert "已执行发布：否" in markdown
        assert "## 优化草稿" in markdown
        assert "## 风控复检" in markdown
