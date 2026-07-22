import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

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

test("shows sources, extraction result, version diff, and requires confirmation", async () => {
  render(<StyleProfileCenter accountId="account-1" workspaceId="workspace-1" />);

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
  render(<StyleProfileCenter accountId="account-1" workspaceId="workspace-1" />);
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
  render(
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
