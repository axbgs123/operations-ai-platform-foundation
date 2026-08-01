import { cleanup, fireEvent, render as rtlRender, screen, waitFor } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { WorkspaceShell } from "@/components/workbench/workspace-shell";
import {
  confirmStyleProfile,
  extractStyleProfile,
  listStyleCandidates,
  listStyleProfiles,
  listStyleSamples,
  listStyleScopes,
  selectStyleSample,
} from "@/lib/style-api";

import { StyleProfileCenter } from "./style-profile-center";

vi.mock("next/navigation", () => ({
  usePathname: () => "/workspaces/workspace-1/styles/account-1",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

const candidate = {
  content_id: "content-2",
  title: "待选择的已发布内容",
  published_at: "2026-07-22T08:00:00Z",
  selected: false,
};
const sample = {
  id: "sample-1",
  content_id: "content-1",
  title: "三秒看懂 AI 工具",
  selected_by: "member-1",
  selected_at: "2026-07-22T08:05:00Z",
};
const pendingProfile = {
  id: "profile-2",
  workspace_id: "workspace-1",
  account_id: "account-1",
  scope_key: "account",
  column_campaign_id: null,
  version: 2,
  status: "pending_confirmation" as const,
  style: {
    title: {
      length: { minimum: 8, maximum: 18 },
      sentence_patterns: ["statement"],
      hooks: ["先看结论"],
      frequent_words: ["AI 工具"],
      punctuation: ["！"],
      emojis: ["✨"],
    },
    copy: {
      tones: ["direct"],
      openings: ["先说结论"],
      paragraph_structure: ["short_paragraphs"],
      information_density: "medium",
      calls_to_action: ["马上收藏"],
    },
    cover: {
      colors: ["cyan"],
      fonts: ["sans"],
      size_hierarchy: ["title-large"],
      text_positions: ["top-left"],
      logos: ["brand-mark"],
      compositions: ["subject-right"],
      whitespace: ["generous"],
    },
    prohibited: {
      expressions: ["绝对第一"],
      colors: ["neon-red"],
      layouts: ["dense-grid"],
      visual_styles: ["low-contrast"],
    },
  },
  sample_sources: [
    {
      content_id: sample.content_id,
      title: sample.title,
      published_at: "2026-07-21T08:00:00Z",
    },
  ],
  diff: { base_version: 1, changed_sections: ["title", "copy"] },
  confirmed_by: null,
  confirmed_at: null,
};

const shellContext = {
  workspace_id: "workspace-1",
  workspace_name: "运营工作区",
  member_id: "member-admin",
  member_display_name: "运营管理员",
  role: "admin" as const,
  accounts: [],
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

vi.mock("@/lib/style-api", () => ({
  confirmStyleProfile: vi.fn(),
  extractStyleProfile: vi.fn(),
  listStyleCandidates: vi.fn(),
  listStyleProfiles: vi.fn(),
  listStyleSamples: vi.fn(),
  listStyleScopes: vi.fn(),
  selectStyleSample: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  });
  sessionStorage.setItem("workspace_csrf", "csrf-token");
  vi.mocked(listStyleCandidates).mockResolvedValue([candidate]);
  vi.mocked(listStyleSamples).mockResolvedValue([sample]);
  vi.mocked(listStyleProfiles).mockResolvedValue([pendingProfile]);
  vi.mocked(listStyleScopes).mockResolvedValue([
    {
      id: "column-1",
      name: "暑期栏目",
      kind: "column",
      starts_at: "2026-08-01T00:00:00Z",
      ends_at: "2026-08-31T23:59:59Z",
      objective_profile_id: null,
      benchmark_profile_id: null,
    },
  ]);
  vi.mocked(selectStyleSample).mockResolvedValue({
    ...sample,
    id: "sample-2",
    content_id: candidate.content_id,
    title: candidate.title,
  });
  vi.mocked(extractStyleProfile).mockResolvedValue(pendingProfile);
  vi.mocked(confirmStyleProfile).mockResolvedValue({
    ...pendingProfile,
    status: "confirmed",
    confirmed_by: "member-1",
    confirmed_at: "2026-07-22T09:00:00Z",
  });
});

afterEach(cleanup);

test("uses the catalog as the only easy style boundary and shows one activation hint", async () => {
  renderInWorkspace(
    <StyleProfileCenter accountId="account-1" workspaceId="workspace-1" />,
  );

  expect(await screen.findAllByText(
    "用人工确认的样本稳定账号表达；优秀内容结构不会自动变成账号风格。",
  )).toHaveLength(1);
  expect(screen.getAllByText(
    "只有人工选择并确认的风格版本才会生效。",
  )).toHaveLength(1);
  expect(screen.queryByText(
    "账号 Style Profile 与已确认 Viral Reference 保持独立版本和引用边界。",
  )).not.toBeInTheDocument();
  expect(screen.queryByText(
    "账号风格用于稳定表达；爆款结构只是人工确认的策略参考，二者不会自动合并。",
  )).not.toBeInTheDocument();
});

test("shows one professional style boundary without easy or static duplicates", async () => {
  localStorage.setItem("operations-ai:copy-mode:member-admin", "professional");
  renderInWorkspace(
    <StyleProfileCenter accountId="account-1" workspaceId="workspace-1" />,
  );

  expect(await screen.findByText(/版本确认/)).toBeVisible();
  expect(screen.getAllByText(
    "账号 Style Profile 与已确认 Viral Reference 保持独立版本和引用边界。",
  )).toHaveLength(1);
  expect(screen.queryByText(
    "只有人工选择并确认的风格版本才会生效。",
  )).not.toBeInTheDocument();
  expect(screen.queryByText(
    "账号风格用于稳定表达；爆款结构只是人工确认的策略参考，二者不会自动合并。",
  )).not.toBeInTheDocument();
});

test("shows sources, extraction result, version diff, and requires confirmation", async () => {
  renderInWorkspace(<StyleProfileCenter accountId="account-1" workspaceId="workspace-1" />);

  expect(await screen.findByRole("heading", { name: "账号风格中心" })).toBeInTheDocument();
  expect(screen.getByText("三秒看懂 AI 工具")).toBeInTheDocument();
  expect(screen.getByText("待选择的已发布内容")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "暑期栏目" })).toHaveAttribute(
    "href",
    "/workspaces/workspace-1/styles/account-1?columnCampaignId=column-1",
  );
  expect(screen.getByText("待确认 · v2")).toBeInTheDocument();
  expect(screen.getByText("相对 v1 变化：标题、文案")).toBeInTheDocument();
  expect(screen.getByText("标题钩子：先看结论")).toBeInTheDocument();
  expect(screen.getByText("文案语气：direct")).toBeInTheDocument();
  expect(screen.getByText("封面配色：cyan")).toBeInTheDocument();
  expect(screen.getByText("禁止表达：绝对第一")).toBeInTheDocument();
  await waitFor(() => {
    expect(screen.getByLabelText("禁止表达")).toHaveValue("绝对第一");
    expect(screen.getByLabelText("禁止颜色")).toHaveValue("neon-red");
  });

  fireEvent.click(screen.getByRole("button", { name: "选择为风格样本" }));
  await waitFor(() => {
    expect(selectStyleSample).toHaveBeenCalledWith(
      "workspace-1",
      "account-1",
      "content-2",
      "csrf-token",
      null,
    );
  });

  fireEvent.change(screen.getByLabelText("禁止表达"), {
    target: { value: "绝对第一, 永久有效" },
  });
  fireEvent.change(screen.getByLabelText("禁止颜色"), {
    target: { value: "neon-red" },
  });
  fireEvent.change(screen.getByLabelText("禁止版式"), {
    target: { value: "dense-grid" },
  });
  fireEvent.change(screen.getByLabelText("禁止视觉风格"), {
    target: { value: "low-contrast" },
  });
  fireEvent.click(screen.getByRole("button", { name: "重新提取风格档案" }));
  await waitFor(() => {
    expect(extractStyleProfile).toHaveBeenCalledWith(
      "workspace-1",
      "account-1",
      "csrf-token",
      null,
      {
        expressions: ["绝对第一", "永久有效"],
        colors: ["neon-red"],
        layouts: ["dense-grid"],
        visual_styles: ["low-contrast"],
      },
    );
  });

  fireEvent.click(screen.getByRole("button", { name: "确认并启用 v2" }));
  await waitFor(() => {
    expect(confirmStyleProfile).toHaveBeenCalledWith(
      "workspace-1",
      "profile-2",
      "csrf-token",
    );
  });
});

test("defaults to all style inheritance and lets each type be disabled", async () => {
  renderInWorkspace(<StyleProfileCenter accountId="account-1" workspaceId="workspace-1" />);
  await screen.findByRole("heading", { name: "账号风格中心" });

  const title = screen.getByRole("checkbox", { name: "沿用标题风格" });
  const copy = screen.getByRole("checkbox", { name: "沿用文案风格" });
  const cover = screen.getByRole("checkbox", { name: "沿用封面风格" });
  expect(title).toBeChecked();
  expect(copy).toBeChecked();
  expect(cover).toBeChecked();

  fireEvent.click(title);
  fireEvent.click(copy);
  fireEvent.click(cover);
  expect(title).not.toBeChecked();
  expect(copy).not.toBeChecked();
  expect(cover).not.toBeChecked();
  expect(screen.getByText("当前生成上下文不会引用任何历史风格")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "一键沿用全部风格" }));
  expect(title).toBeChecked();
  expect(copy).toBeChecked();
  expect(cover).toBeChecked();
});

test("extracts a column-specific profile when opened for a column", async () => {
  vi.mocked(listStyleProfiles).mockResolvedValue([
    {
      ...pendingProfile,
      scope_key: "column:column-1",
      column_campaign_id: "column-1",
    },
    {
      ...pendingProfile,
      id: "account-profile-99",
      version: 99,
      scope_key: "account",
      column_campaign_id: null,
    },
    {
      ...pendingProfile,
      id: "deleted-column-profile-100",
      version: 100,
      scope_key: "column:deleted-column",
      column_campaign_id: null,
    },
  ]);
  renderInWorkspace(
    <StyleProfileCenter
      accountId="account-1"
      columnCampaignId="column-1"
      workspaceId="workspace-1"
    />,
  );
  await screen.findByRole("heading", { name: "账号风格中心" });
  expect(screen.getByText("待确认 · v2")).toBeInTheDocument();
  await waitFor(() => {
    expect(screen.getByLabelText("禁止表达")).toHaveValue("绝对第一");
  });

  fireEvent.click(screen.getByRole("button", { name: "重新提取风格档案" }));

  await waitFor(() => {
    expect(extractStyleProfile).toHaveBeenCalledWith(
      "workspace-1",
      "account-1",
      "csrf-token",
      "column-1",
      {
        expressions: ["绝对第一"],
        colors: ["neon-red"],
        layouts: ["dense-grid"],
        visual_styles: ["low-contrast"],
      },
    );
  });
});

test("separates title copy and cover style with traceable account scope", async () => {
  renderInWorkspace(<StyleProfileCenter accountId="account-1" workspaceId="workspace-1" />);

  expect(await screen.findByRole("heading", { name: "标题风格" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "文案风格" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "封面风格" })).toBeVisible();
  expect(screen.getByText("长度：8—18")).toBeVisible();
  expect(screen.getByText("句式：statement")).toBeVisible();
  expect(screen.getByText("开头：先说结论")).toBeVisible();
  expect(screen.getByText("构图：subject-right")).toBeVisible();
  expect(screen.getByText("当前账号范围：account-1")).toBeVisible();
  expect(screen.getByText("生成预设合同：当前记录未提供")).toBeVisible();
  expect(screen.getByText("历史版本")).toBeVisible();
});

test("explains temporary column override and restoration", async () => {
  vi.mocked(listStyleProfiles).mockResolvedValue([{
    ...pendingProfile,
    scope_key: "column:column-1",
    column_campaign_id: "column-1",
  }]);
  renderInWorkspace(
    <StyleProfileCenter
      accountId="account-1"
      columnCampaignId="column-1"
      workspaceId="workspace-1"
    />,
  );

  expect(await screen.findByText("当前为栏目/活动临时覆盖")).toBeVisible();
  expect(screen.getByText("覆盖生效：2026-08-01T00:00:00Z")).toBeVisible();
  expect(screen.getByText("覆盖结束：2026-08-31T23:59:59Z")).toBeVisible();
  expect(screen.getByText("覆盖结束后恢复账号默认风格")).toBeVisible();
});

test("viewer sees historical styles without write controls", async () => {
  renderInWorkspace(
    <StyleProfileCenter
      accountId="account-1"
      role="viewer"
      workspaceId="workspace-1"
    />,
    "viewer",
  );
  expect(await screen.findByRole("heading", { name: "标题风格" })).toBeVisible();
  expect(screen.queryByRole("button", { name: "重新提取风格档案" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "选择为风格样本" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "确认并启用 v2" })).not.toBeInTheDocument();
  expect(screen.getByText("建议先做").closest("p")).not.toHaveTextContent(
    /确认候选|确认新版本|添加来源|开始生成/,
  );
  expect(screen.getByText("查看者可查看历史风格，不能选择样本、提取或确认版本")).toBeVisible();
});

test("stacks the three style sections before the desktop breakpoint", async () => {
  renderInWorkspace(<StyleProfileCenter accountId="account-1" workspaceId="workspace-1" />);
  expect(await screen.findByTestId("style-sections")).toHaveClass("grid-cols-1");
  expect(screen.getByTestId("style-sections")).toHaveClass("lg:grid-cols-3");
});
