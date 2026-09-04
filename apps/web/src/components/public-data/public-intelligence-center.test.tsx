import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { PublicIntelligenceCenter } from "./public-intelligence-center";

const api = vi.hoisted(() => ({
  create: vi.fn(),
  collect: vi.fn(),
  analyze: vi.fn(),
  search: vi.fn(),
}));

vi.mock("@/components/workbench/workspace-shell", () => ({
  useWorkbenchShellContext: () => ({ role: "editor" }),
}));

vi.mock("@/lib/public-data-api", () => ({
  getCompetitorAccounts: vi.fn().mockResolvedValue([]),
  getCommentDemands: vi.fn().mockResolvedValue([]),
  getPublicOperationsReport: vi.fn().mockResolvedValue({
    generated_at: "2026-09-04T08:00:00Z",
    own_updates_24h: 2,
    monitored_accounts: 0,
    comment_analyses_24h: 0,
    alerts: [],
    actions: ["添加对标账号。"],
  }),
  getPublicTrendSearches: vi.fn().mockResolvedValue([]),
  createCompetitorAccount: (...args: unknown[]) => api.create(...args),
  collectCompetitorAccount: (...args: unknown[]) => api.collect(...args),
  analyzeCommentDemands: (...args: unknown[]) => api.analyze(...args),
  searchPublicTrends: (...args: unknown[]) => api.search(...args),
}));

beforeEach(() => {
  api.create.mockReset();
  api.collect.mockReset();
  api.analyze.mockReset();
  api.search.mockReset();
  sessionStorage.setItem("workspace_csrf", "csrf-test");
});
afterEach(cleanup);

test("shows the daily report and explains empty intelligence data", async () => {
  render(<PublicIntelligenceCenter workspaceId="workspace-1" />);

  expect(await screen.findByText("今日运营简报")).toBeVisible();
  expect(screen.getByText("自己的数据更新")).toBeVisible();
  expect(screen.getByText("还没有对标账号")).toBeVisible();
  expect(screen.getByText("还没有评论分析")).toBeVisible();
  expect(screen.getByText("还没有搜索记录")).toBeVisible();
});

test("adds a competitor and immediately starts the first collection", async () => {
  api.create.mockResolvedValue({ id: "competitor-1" });
  api.collect.mockResolvedValue({ id: "competitor-1" });
  render(<PublicIntelligenceCenter workspaceId="workspace-1" />);

  await screen.findByText("今日运营简报");
  await userEvent.type(screen.getByLabelText("账号备注名"), "同赛道账号");
  await userEvent.type(
    screen.getByLabelText("公开主页链接"),
    "https://www.douyin.com/user/sec-user-1",
  );
  await userEvent.click(screen.getByRole("button", { name: "添加并采集" }));

  expect(api.create).toHaveBeenCalledWith(
    "workspace-1",
    "csrf-test",
    expect.objectContaining({ name: "同赛道账号", platform: "douyin" }),
  );
  expect(api.collect).toHaveBeenCalledWith(
    "workspace-1",
    "competitor-1",
    "csrf-test",
  );
  expect(await screen.findByText(/完成第一次采集/)).toBeVisible();
});
