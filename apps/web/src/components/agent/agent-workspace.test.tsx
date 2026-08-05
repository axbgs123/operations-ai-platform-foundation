import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { visibleNavigationItems } from "@/components/workbench/navigation";
import { ExperiencePreferencesProvider } from "@/components/workbench/experience-preferences-context";
import { WorkspaceTopbar } from "@/components/workbench/workspace-topbar";
import type {
  AgentConfirmationData,
  AgentPlanData,
  AgentRunData,
  AgentWorkspaceFixture,
} from "@/lib/agent-api";

import { AgentWorkspace } from "./agent-workspace";


const account = {
  account_id: "11111111-1111-4111-8111-111111111111",
  name: "抖音科技账号",
  platform: "douyin" as const,
};

const plan: AgentPlanData = {
  id: "22222222-2222-4222-8222-222222222222",
  workspace_id: "33333333-3333-4333-8333-333333333333",
  briefing_id: "44444444-4444-4444-8444-444444444444",
  account_id: account.account_id,
  platform: "douyin",
  status: "draft",
  document: {
    goal: "优化最近一条表现下降的内容",
    platform: "douyin",
    account_id: account.account_id,
    candidate_id: "c".repeat(64),
    input_fingerprint: "a".repeat(64),
    tool_catalog_version: "operations-agent-tools-v1",
    steps: [
      {
        step_index: 0,
        tool_name: "generate_optimization_draft",
        tool_version: "1.0.0",
        arguments: {},
        rationale: "生成一份可人工修改的优化草稿。",
      },
    ],
  },
  approval_snapshot: {
    briefing_input_fingerprint: "a".repeat(64),
    account_configuration_version: "b".repeat(64),
    model_configuration_version: "c".repeat(64),
    risk_rule_version: "d".repeat(64),
  },
  plan_fingerprint: "e".repeat(64),
  tool_catalog_version: "operations-agent-tools-v1",
  approved_by: null,
  approved_at: null,
  created_at: "2026-08-05T08:00:00Z",
  usage: {
    uses_external_api: true,
    provider: "qianwen",
    model_id: "qwen3.5-plus-2026-04-20",
    attempt_count: 0,
    input_tokens: 0,
    output_tokens: 0,
    embedding_tokens: 0,
    ocr_images: 0,
    generated_images: 0,
    usage_status: "not_used",
  },
};

const running: AgentRunData = {
  id: "55555555-5555-4555-8555-555555555555",
  workspace_id: plan.workspace_id,
  plan_id: plan.id,
  account_id: account.account_id,
  platform: "douyin",
  status: "running",
  current_step_index: 0,
  safe_error_code: null,
  created_at: "2026-08-05T08:02:00Z",
  updated_at: "2026-08-05T08:03:00Z",
  completed_at: null,
  steps: [
    {
      id: "66666666-6666-4666-8666-666666666666",
      step_index: 0,
      tool_name: "generate_optimization_draft",
      tool_version: "1.0.0",
      tool_risk: "draft_write",
      status: "running",
      attempt_count: 1,
      safe_summary: null,
      safe_error_code: null,
      started_at: "2026-08-05T08:03:00Z",
      completed_at: null,
    },
  ],
  usage: plan.usage,
};

const confirmation: AgentConfirmationData = {
  id: "77777777-7777-4777-8777-777777777777",
  run_id: running.id,
  step_id: running.steps[0].id,
  status: "pending",
  action_fingerprint: "f".repeat(64),
  tool_name: "create_agent_export",
  tool_version: "1.0.0",
  risk: "protected_write",
  argument_keys: ["account_id"],
  expires_at: "2026-08-05T08:15:00Z",
  resolved_at: null,
  created_at: "2026-08-05T08:05:00Z",
};

const fixture: AgentWorkspaceFixture = {
  accounts: [account],
  briefing: {
    id: plan.briefing_id,
    workspace_id: plan.workspace_id,
    input_fingerprint: "a".repeat(64),
    algorithm_version: "operations-agent-briefing-v1",
    tool_catalog_version: "operations-agent-tools-v1",
    data_cutoff_at: "2026-08-05T08:00:00Z",
    primary: {
      candidate_id: "c".repeat(64),
      kind: "pending_analysis",
      platform: "douyin",
      account_id: account.account_id,
      content_id: "88888888-8888-4888-8888-888888888888",
      is_primary: true,
      safe_title: "先处理最近表现下降的内容",
      safe_reason: "已有确认数据，可以开始分析并生成优化草稿。",
      blocking_rank: 1,
      severity_rank: 1,
      evidence_rank: 5,
      objective_rank: 5,
      executable_rank: 5,
      repeat_penalty: 0,
      evidence_refs: [
        "content:88888888-8888-4888-8888-888888888888",
      ],
    },
    candidates: [],
    created_at: "2026-08-05T08:01:00Z",
  },
  plan,
  run: running,
  confirmations: [],
};

beforeEach(() => {
  localStorage.clear();
  sessionStorage.setItem("workspace_csrf", "csrf-token");
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

test("viewer sees durable progress but no plan approval buttons", () => {
  render(
    <AgentWorkspace
      actions={{}}
      fixture={fixture}
      role="viewer"
      workspaceId={plan.workspace_id}
    />,
  );

  expect(screen.getByText("正在生成优化草稿")).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "批准计划" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByText("查看者可以查看进度和结果，但不能批准或执行操作。"),
  ).toBeVisible();
});

test("restores pending confirmation from server state without local action data", () => {
  render(
    <AgentWorkspace
      actions={{}}
      fixture={{ ...fixture, confirmations: [confirmation] }}
      role="admin"
      workspaceId={plan.workspace_id}
    />,
  );

  expect(
    screen.getByRole("heading", { name: "需要你确认" }),
  ).toBeVisible();
  expect(screen.getByText("创建执行报告")).toBeVisible();
  expect(screen.getByText("这一步需要你确认后才会继续。")).toBeVisible();
  expect(localStorage.length).toBe(0);
});

test("accepts an operator goal and locks one account before plan creation", async () => {
  const createPlan = vi.fn();
  const user = userEvent.setup();
  render(
    <AgentWorkspace
      actions={{ createPlan }}
      fixture={{ ...fixture, plan: undefined, run: undefined }}
      role="editor"
      workspaceId={plan.workspace_id}
    />,
  );

  await user.clear(screen.getByLabelText("这次想解决什么"));
  await user.type(
    screen.getByLabelText("这次想解决什么"),
    "优化最近一条表现下降的内容",
  );
  await user.selectOptions(
    screen.getByLabelText("执行账号"),
    account.account_id,
  );
  await user.click(
    screen.getByRole("button", { name: "生成处理计划" }),
  );

  expect(createPlan).toHaveBeenCalledWith({
    objective: "优化最近一条表现下降的内容",
    account_id: account.account_id,
    platform: "douyin",
    briefing_id: fixture.briefing.id,
    planner: "deterministic",
  });
});

test("can resume an approved plan when execution was not started", async () => {
  const startRun = vi.fn().mockResolvedValue(running);
  const user = userEvent.setup();
  render(
    <AgentWorkspace
      actions={{ startRun }}
      fixture={{
        ...fixture,
        plan: {
          ...plan,
          status: "approved",
          approved_by: "99999999-9999-4999-8999-999999999999",
          approved_at: "2026-08-05T08:02:00Z",
        },
        run: undefined,
      }}
      role="editor"
      workspaceId={plan.workspace_id}
    />,
  );

  await user.click(screen.getByRole("button", { name: "开始执行" }));

  expect(startRun).toHaveBeenCalledWith(
    expect.objectContaining({ id: plan.id, status: "approved" }),
  );
  expect(screen.getByText("正在生成优化草稿")).toBeVisible();
});

test("adds the agent as one creation module for every private role", () => {
  for (const role of ["admin", "editor", "viewer"] as const) {
    expect(
      visibleNavigationItems(role).filter(
        (item) => item.label === "运营智能体",
      ),
    ).toHaveLength(1);
  }
});

test("topbar shows only the server-backed pending count without action details", async () => {
  const loadConfirmations = vi.fn().mockResolvedValue({
    items: [confirmation],
  });
  render(
    <ExperiencePreferencesProvider memberId="99999999-9999-4999-8999-999999999999">
      <WorkspaceTopbar
        context={{
          workspace_id: plan.workspace_id,
          workspace_name: "测试工作区",
          member_id: "99999999-9999-4999-8999-999999999999",
          member_display_name: "运营成员",
          role: "admin",
          accounts: [account],
          failed_task_count: 0,
        }}
        isMobile={false}
        loadConfirmations={loadConfirmations}
        navigationTriggerRef={{ current: null }}
        onOpenNavigation={vi.fn()}
        onScopeChange={vi.fn()}
        pathname={`/workspaces/${plan.workspace_id}`}
        scope={{}}
      />
    </ExperiencePreferencesProvider>,
  );

  await waitFor(() => {
    expect(
      screen.getByRole("link", { name: "1 个操作待确认" }),
    ).toBeVisible();
  });
  expect(screen.queryByText("create_agent_export")).not.toBeInTheDocument();
  expect(loadConfirmations).toHaveBeenCalledWith(
    plan.workspace_id,
    expect.any(AbortSignal),
  );
});
