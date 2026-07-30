import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";

import {
  GenerationWizard,
  generationDraftStorageKey,
  normalizeGenerationStep,
  serializeSafeGenerationDraft,
  type GenerationWizardFixture,
} from "./generation-wizard";


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
      column_campaign_id: null,
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

test("defines the five safe steps and defaults independent style inheritance on", () => {
  render(
    <GenerationWizard
      fixture={fixture}
      initialStep="references"
      role="editor"
      workspaceId="workspace-1"
    />,
  );

  for (const label of ["范围与目标", "事实资料", "风格与参考", "生成与编辑", "复核与保存"]) {
    expect(screen.getByRole("button", { name: new RegExp(label) })).toBeVisible();
  }
  expect(screen.getByRole("checkbox", { name: "沿用标题风格" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "沿用文案风格" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "沿用封面风格" })).toBeChecked();
  expect(screen.getByText("Provider experimental")).toBeVisible();
  expect(screen.getByText("账号风格版本：v3")).toBeVisible();
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
  const { rerender } = render(
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
  render(
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
  render(
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
  render(
    <GenerationWizard
      fixture={fixture}
      initialStep="generate"
      role="viewer"
      workspaceId="workspace-1"
    />,
  );
  expect(screen.getByText(/查看者只能查看生成状态/)).toBeVisible();
  expect(screen.queryByRole("button", { name: /生成|保存|复检/ })).not.toBeInTheDocument();
  expect(screen.getByText("请在电脑端继续复杂封面编辑。")).toBeVisible();
  expect(document.body.textContent).not.toContain("Provider Workspace ID");
  expect(document.body.textContent).not.toContain("API Key");
});

test("clears incompatible dependent scope when platform changes", () => {
  const onStateChange = vi.fn();
  const onPlatformChange = vi.fn();
  render(
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
  const { rerender } = render(
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
