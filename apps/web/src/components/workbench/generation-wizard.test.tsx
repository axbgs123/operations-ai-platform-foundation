import {
  cleanup,
  fireEvent,
  render as rtlRender,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement, ReactNode } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { WorkspaceShell } from "@/components/workbench/workspace-shell";

import {
  GenerationWizard,
  generationDraftStorageKey,
  normalizeGenerationStep,
  serializeSafeGenerationDraft,
  type GenerationWizardFixture,
} from "./generation-wizard";

const textEditorMockState = vi.hoisted(() => ({ draft: null as unknown }));
const editTextGenerationMock = vi.hoisted(() => vi.fn());

vi.mock("next/navigation", () => ({
  usePathname: () => "/workspaces/workspace-1/generation",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/app/workspaces/[workspaceId]/generation/text-editor", () => ({
  TextEditor: ({
    onDraftChange,
  }: {
    onDraftChange?: (draft: unknown) => void;
  }) => (
    <button
      onClick={() => onDraftChange?.(textEditorMockState.draft)}
      type="button"
    >
      载入合成生成结果
    </button>
  ),
}));

vi.mock("@/lib/generation-api", () => ({
  editTextGeneration: editTextGenerationMock,
}));

beforeEach(() => {
  localStorage.clear();
  textEditorMockState.draft = null;
  editTextGenerationMock.mockReset();
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
  sessionStorage.clear();
});

const fixture: GenerationWizardFixture = {
  accounts: [
    { account_id: "dy-1", platform: "douyin", name: "抖音账号" },
    { account_id: "xhs-1", platform: "xiaohongshu", name: "小红书账号" },
  ],
  columns: [
    {
      id: "column-1",
      workspace_id: "workspace-1",
      account_id: "dy-1",
      name: "AI 栏目",
      kind: "column",
      starts_at: null,
      ends_at: null,
      configuration_override: {},
      created_at: "2026-07-30T00:00:00Z",
    },
  ],
  models: [
    {
      id: "model-1",
      provider: "mock-contract",
      model_id: "mock-text-v1",
      region: null,
      capability: "text",
      status: "experimental",
      experimental: true,
      credential_configured: true,
      credential_updated_at: "2026-07-30T00:00:00Z",
      configuration_version: "config-v1",
      contract_version: "mock-contract-v1",
      last_validation_status: "not_run",
      last_validated_at: null,
      safe_error_code: null,
    },
  ],
  factSources: [],
  factContext: {
    unconstrained_facts: true,
    has_sources: false,
    requires_confirmation: false,
    confirmed_items: [],
  },
  styles: [
    {
      id: "style-1",
      workspace_id: "workspace-1",
      account_id: "dy-1",
      scope_key: "account",
      column_campaign_id: "column-1",
      version: 3,
      status: "confirmed",
      style: {},
      sample_sources: [],
      diff: {},
      confirmed_by: "member-1",
      confirmed_at: "2026-07-30T00:00:00Z",
    },
  ],
  viralItems: Array.from({ length: 4 }, (_, index) => ({
    id: `viral-${index + 1}`,
    candidate_id: `candidate-${index + 1}`,
    account_id: "dy-1",
    content_id: `content-${index + 1}`,
    platform: "douyin",
    category: "traffic",
    title: `已确认素材 ${index + 1}`,
    strategy_tags: ["结果前置"],
    applicable_scenarios: ["新品讲解"],
    structure_summary: "痛点—证据—行动",
    confirmed_by: "member-1",
    confirmed_at: "2026-07-30T00:00:00Z",
    active: true,
    revoked_at: null,
    revocation_reason: null,
    generation_eligible: true,
  })),
  riskScan: null,
};

const populatedGenerationDraft = {
  run: {
    id: "run-1",
    workspace_id: "workspace-1",
    account_id: "dy-1",
    model_config_id: "model-1",
    status: "succeeded",
    status_detail: "provider_calling lease_17",
    adoption_status: "pending",
    context: {
      model: {
        contract_version: "mock-contract-v1",
        configuration_version: "config-v1",
      },
    },
    modification_magnitude: 0.125,
  },
  finalTitle: "已生成标题",
  finalCopy: "已生成正文",
};

const shellContext = {
  workspace_id: "workspace-1",
  workspace_name: "运营工作区",
  member_id: "member-admin",
  member_display_name: "运营管理员",
  role: "admin" as const,
  accounts: fixture.accounts,
  failed_task_count: 0,
};

function renderInWorkspace(
  ui: ReactElement,
  role: "admin" | "editor" | "viewer" = "admin",
) {
  return rtlRender(ui, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <WorkspaceShell context={{ ...shellContext, role }}>
        {children}
      </WorkspaceShell>
    ),
  });
}

test("explains the easy generation purpose and all five safe steps", () => {
  renderInWorkspace(
    <GenerationWizard
      fixture={fixture}
      initialStep="review"
      role="editor"
      workspaceId="workspace-1"
    />,
    "editor",
  );

  expect(screen.getByText(
    "根据已确认的事实、账号风格和参考内容，生成标题、文案和封面。",
  )).toBeVisible();
  for (const description of [
    "先选择平台、账号和栏目，后面的事实、风格和参考只在这个范围内使用。",
    "选择可以确认的资料；未确认或互相冲突的内容不能直接写进确定性文案。",
    "决定是否沿用账号风格，并选择最多三条已确认的优秀内容作为参考。",
    "生成标题、文案和封面后可以修改；参考图片发送范围会在调用前说明。",
    "再次检查事实、风格和发布风险，通过后再保存。",
  ]) {
    expect(screen.getByText(description)).toBeVisible();
  }
  expect(screen.getByText("辅助判断，不保证通过平台审核")).toBeVisible();
});

test("keeps populated generation review operator-facing in easy mode", () => {
  const easy = renderInWorkspace(
    <GenerationWizard
      fixture={fixture}
      initialStep="review"
      role="editor"
      workspaceId="workspace-1"
    />,
  );

  for (const label of ["范围与目标", "事实资料", "风格与参考", "生成与编辑", "复核与保存"]) {
    expect(
      screen.getAllByRole("button", { name: new RegExp(label) }).length,
    ).toBeGreaterThan(0);
  }
  expect(screen.getByText("模型服务")).toBeVisible();
  expect(screen.getAllByText(/检查规则/).length).toBeGreaterThan(0);
  expect(screen.getAllByText(/图片文字识别/).length).toBeGreaterThan(0);
  expect(screen.getByText(
    "试用状态，真实效果和费用尚未完成验收",
  )).toBeVisible();
  expect(easy.container.textContent).not.toMatch(
    /\b(?:Chunk|Citation|Evidence Bundle|Mock|RAG|OCR|Embedding|Provider|Prompt|Worker|lease|heartbeat|INSUFFICIENT_SAMPLE)\b/,
  );
  expect(easy.container.textContent).not.toMatch(
    /mock-contract-v1|config-v1|\bexperimental\b|门禁|向量/,
  );
});

test("preserves exact professional generation terminology and model versions", () => {
  localStorage.setItem("operations-ai:copy-mode:member-admin", "professional");
  const professional = renderInWorkspace(
    <GenerationWizard
      fixture={fixture}
      initialStep="review"
      role="editor"
      workspaceId="workspace-1"
    />,
  );

  expect(screen.getByText("Provider experimental")).toBeVisible();
  expect(professional.container).toHaveTextContent("门禁");
  expect(professional.container).toHaveTextContent("OCR");
  expect(professional.container).toHaveTextContent("mock-text-v1");
  expect(professional.container).toHaveTextContent("mock-contract-v1");
  expect(professional.container).toHaveTextContent("config-v1");
});

test("hides generation runtime detail and review error codes in easy mode", async () => {
  const user = userEvent.setup();
  textEditorMockState.draft = populatedGenerationDraft;
  editTextGenerationMock.mockRejectedValue(
    new Error("MODEL_PROVIDER_UNAVAILABLE"),
  );
  const easy = renderInWorkspace(
    <GenerationWizard
      fixture={fixture}
      initialAccountId="dy-1"
      initialStep="generate"
      role="editor"
      workspaceId="workspace-1"
    />,
  );

  await user.click(screen.getByRole("button", { name: "载入合成生成结果" }));
  await user.click(screen.getByRole("button", { name: "下一步：复核与保存" }));

  expect(easy.container).toHaveTextContent("已完成");
  expect(easy.container).toHaveTextContent("等待决定");
  expect(screen.getByText(
    "处理详情已记录，可在专业模式查看",
  )).toBeVisible();
  expect(easy.container).not.toHaveTextContent("provider_calling lease_17");

  await user.click(screen.getByRole("button", { name: "复检并保存草稿" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "复核暂时无法完成，请稍后重试；如持续失败请联系管理员。",
  );
  expect(easy.container).not.toHaveTextContent("MODEL_PROVIDER_UNAVAILABLE");
});

test("preserves exact generation runtime detail and review errors in professional mode", async () => {
  const user = userEvent.setup();
  localStorage.setItem("operations-ai:copy-mode:member-admin", "professional");
  textEditorMockState.draft = populatedGenerationDraft;
  editTextGenerationMock.mockRejectedValue(
    new Error("MODEL_PROVIDER_UNAVAILABLE"),
  );
  renderInWorkspace(
    <GenerationWizard
      fixture={fixture}
      initialAccountId="dy-1"
      initialStep="generate"
      role="editor"
      workspaceId="workspace-1"
    />,
  );

  await user.click(screen.getByRole("button", { name: "载入合成生成结果" }));
  await user.click(screen.getByRole("button", { name: "下一步：复核与保存" }));

  expect(screen.getByText("provider_calling lease_17")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "复检并保存草稿" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "MODEL_PROVIDER_UNAVAILABLE",
  );
});

test("defaults independent style inheritance on", () => {
  const easy = renderInWorkspace(
    <GenerationWizard
      fixture={fixture}
      initialStep="references"
      role="editor"
      workspaceId="workspace-1"
    />,
  );

  expect(screen.getByRole("checkbox", { name: "沿用标题风格" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "沿用文案风格" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "沿用封面风格" })).toBeChecked();
  expect(screen.getByText(
    "试用状态，真实效果和费用尚未完成验收",
  )).toBeVisible();
  expect(screen.getByText(
    "账号风格版本：已记录，可在专业模式查看",
  )).toBeVisible();
  expect(screen.getByText("栏目临时覆盖：AI 栏目")).toBeVisible();
  expect(easy.container).not.toHaveTextContent("账号风格版本：v3");
  expect(easy.container).not.toHaveTextContent("column-1");
});

test("uses the selected column display name instead of its identifier in easy mode", () => {
  sessionStorage.setItem(
    generationDraftStorageKey("workspace-1", "member-1"),
    JSON.stringify({
      step: "references",
      accountId: "dy-1",
      columnId: "column-1",
      objectiveId: null,
      inheritTitleStyle: true,
      inheritCopyStyle: true,
      inheritCoverStyle: true,
      viralReferenceIds: [],
      factSourceIds: [],
    }),
  );
  const easy = renderInWorkspace(
    <GenerationWizard
      fixture={fixture}
      initialStep="references"
      memberId="member-1"
      role="editor"
      workspaceId="workspace-1"
    />,
    "editor",
  );

  expect(screen.getAllByText("AI 栏目").length).toBeGreaterThan(0);
  expect(screen.getByText("栏目临时覆盖：AI 栏目")).toBeVisible();
  expect(easy.container).not.toHaveTextContent("column-1");
  expect(easy.container).not.toHaveTextContent("v3");
});

test("professional mode retains style version, campaign ID, and selected column ID", () => {
  localStorage.setItem("operations-ai:copy-mode:member-admin", "professional");
  sessionStorage.setItem(
    generationDraftStorageKey("workspace-1", "member-1"),
    JSON.stringify({
      step: "references",
      accountId: "dy-1",
      columnId: "column-1",
      objectiveId: null,
      inheritTitleStyle: true,
      inheritCopyStyle: true,
      inheritCoverStyle: true,
      viralReferenceIds: [],
      factSourceIds: [],
    }),
  );
  const professional = renderInWorkspace(
    <GenerationWizard
      fixture={fixture}
      initialStep="references"
      memberId="member-1"
      role="editor"
      workspaceId="workspace-1"
    />,
    "editor",
  );

  expect(screen.getByText("账号风格版本：v3")).toBeVisible();
  expect(screen.getByText("栏目临时覆盖：生效于 column-1")).toBeVisible();
  expect(professional.container).toHaveTextContent("column-1");
});

test("blocks confirmed fact conflicts and permits an explicit unconstrained draft", async () => {
  const user = userEvent.setup();
  const conflicting = {
    ...fixture,
    factSources: [
      {
        id: "source-1",
        workspace_id: "workspace-1",
        kind: "text",
        level: "L2",
        title: "合成事实",
        status: "parsed",
        source_url: null,
        resolved_ips: [],
        file_name: null,
        mime_type: null,
        size: null,
        content_sha256: "a".repeat(64),
        published_at: null,
        accessed_at: null,
        untrusted_data: true,
        status_detail: {},
        items: [
          {
            id: "fact-1",
            source_id: "source-1",
            field_name: "价格",
            field_code: "price",
            value: "99元",
            source_location: "人工合成位置",
            confidence: 1,
            status: "confirmed",
            conflict_status: "unresolved",
            confirmed_by: "member-1",
            confirmed_at: "2026-07-30T00:00:00Z",
            override_record: null,
          },
        ],
        created_at: "2026-07-30T00:00:00Z",
      },
    ],
    factContext: {
      unconstrained_facts: false,
      has_sources: true,
      requires_confirmation: false,
      confirmed_items: [],
    },
  } satisfies GenerationWizardFixture;
  const { rerender } = renderInWorkspace(
    <GenerationWizard
      fixture={conflicting}
      initialStep="facts"
      role="editor"
      workspaceId="workspace-1"
    />,
  );
  await user.click(screen.getByRole("checkbox", { name: /价格.*99元/ }));
  expect(screen.getByText("请先处理高风险事实冲突")).toBeVisible();
  expect(screen.getByRole("button", { name: "下一步：风格与参考" })).toBeDisabled();

  rerender(
    <GenerationWizard
      fixture={fixture}
      initialStep="facts"
      role="editor"
      workspaceId="workspace-1"
    />,
  );
  expect(screen.getByText("无事实资料约束")).toBeVisible();
  expect(
    screen.getByText(/不得补充具体材质、参数、价格、功效或承诺/),
  ).toBeVisible();
});

test("allows only three confirmed viral references and never offers candidates", async () => {
  const user = userEvent.setup();
  renderInWorkspace(
    <GenerationWizard
      fixture={fixture}
      initialStep="references"
      role="editor"
      workspaceId="workspace-1"
    />,
  );
  const choices = screen.getAllByRole("checkbox", { name: /已确认素材/ });
  await user.click(choices[0]);
  await user.click(choices[1]);
  await user.click(choices[2]);
  expect(choices[3]).toBeDisabled();
  expect(screen.getByText("最多选择 3 条已确认素材")).toBeVisible();
  expect(screen.queryByText("候选爆款")).not.toBeInTheDocument();
});

test("persists only safe draft metadata and rejects unknown URL steps", () => {
  expect(normalizeGenerationStep("facts")).toBe("facts");
  expect(normalizeGenerationStep("secrets")).toBe("scope");
  expect(generationDraftStorageKey("workspace-1", "member-1")).toBe(
    "operations-ai:generation-draft:workspace-1:member-1",
  );
  const serialized = serializeSafeGenerationDraft({
    step: "references",
    accountId: "dy-1",
    columnId: "column-1",
    objectiveId: "growth",
    inheritTitleStyle: true,
    inheritCopyStyle: false,
    inheritCoverStyle: true,
    viralReferenceIds: ["viral-1"],
    factSourceIds: ["source-1"],
  });
  expect(serialized).toContain('"step":"references"');
  expect(serialized).not.toContain("Prompt");
  expect(serialized).not.toContain("正文");
  expect(serialized).not.toContain("binary");
});

test("restores only validated member-scoped draft metadata", async () => {
  const user = userEvent.setup();
  sessionStorage.setItem(
    generationDraftStorageKey("workspace-1", "member-1"),
    JSON.stringify({
      step: "review",
      accountId: "dy-1",
      columnId: "column-1",
      objectiveId: "growth",
      inheritTitleStyle: true,
      inheritCopyStyle: true,
      inheritCoverStyle: false,
      viralReferenceIds: ["viral-1", "unknown-viral"],
      factSourceIds: ["unknown-source"],
      prompt: "PRIVATE_PROMPT_MUST_BE_IGNORED",
      bearerToken: "PRIVATE_TOKEN_MUST_BE_IGNORED",
    }),
  );
  renderInWorkspace(
    <GenerationWizard
      fixture={fixture}
      initialStep="scope"
      memberId="member-1"
      role="editor"
      workspaceId="workspace-1"
    />,
  );
  expect(screen.getByLabelText("账号")).toHaveValue("dy-1");
  expect(screen.getByLabelText("生成目标")).toHaveValue("growth");
  await user.click(screen.getByRole("button", { name: "风格与参考" }));
  expect(screen.getByRole("checkbox", { name: "沿用封面风格" })).not.toBeChecked();
  expect(document.body.textContent).not.toContain("PRIVATE_PROMPT_MUST_BE_IGNORED");
  expect(document.body.textContent).not.toContain("PRIVATE_TOKEN_MUST_BE_IGNORED");
});

test("keeps viewers read-only and exposes mobile cover limitation", () => {
  renderInWorkspace(
    <GenerationWizard
      fixture={fixture}
      initialStep="generate"
      role="viewer"
      workspaceId="workspace-1"
    />,
    "viewer",
  );
  expect(screen.getByText(/查看者只能查看生成状态/)).toBeVisible();
  expect(screen.queryByRole("button", { name: /生成|保存|复检/ })).not.toBeInTheDocument();
  expect(screen.getByText("建议先做").closest("p")).not.toHaveTextContent("开始生成");
  expect(screen.getByText("请在电脑端继续复杂封面编辑。")).toBeVisible();
  expect(document.body.textContent).not.toContain("Provider Workspace ID");
  expect(document.body.textContent).not.toContain("API Key");
});

test("clears incompatible dependent scope when platform changes", () => {
  const onStateChange = vi.fn();
  const onPlatformChange = vi.fn();
  renderInWorkspace(
    <GenerationWizard
      fixture={fixture}
      initialStep="scope"
      onPlatformChange={onPlatformChange}
      onStateChange={onStateChange}
      role="editor"
      workspaceId="workspace-1"
    />,
  );
  fireEvent.change(screen.getByLabelText("平台"), {
    target: { value: "xiaohongshu" },
  });
  expect(onStateChange).toHaveBeenLastCalledWith(
    expect.objectContaining({
      accountId: null,
      columnId: null,
      viralReferenceIds: [],
    }),
  );
  expect(onPlatformChange).toHaveBeenCalledWith("xiaohongshu");
  expect(onStateChange.mock.invocationCallOrder[0]).toBeLessThan(
    onPlatformChange.mock.invocationCallOrder[0],
  );
});

test("restores URL-controlled account scope without retaining prior account assets", async () => {
  const { rerender } = renderInWorkspace(
    <GenerationWizard
      fixture={fixture}
      initialAccountId="dy-1"
      initialPlatform="douyin"
      initialStep="scope"
      onStepChange={() => undefined}
      role="editor"
      workspaceId="workspace-1"
    />,
  );
  expect(screen.getByLabelText("账号")).toHaveValue("dy-1");
  expect(screen.getByRole("option", { name: "AI 栏目" })).toBeInTheDocument();

  rerender(
    <GenerationWizard
      fixture={{
        ...fixture,
        columns: [],
        styles: [],
        viralItems: [],
      }}
      initialAccountId="xhs-1"
      initialPlatform="xiaohongshu"
      initialStep="scope"
      onStepChange={() => undefined}
      role="editor"
      workspaceId="workspace-1"
    />,
  );

  await waitFor(() => {
    expect(screen.getByLabelText("账号")).toHaveValue("xhs-1");
  });
  expect(screen.queryByRole("option", { name: "AI 栏目" })).not.toBeInTheDocument();
});
