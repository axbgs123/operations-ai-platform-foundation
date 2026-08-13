import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { HotspotReview } from "./hotspot-review";

const state = vi.hoisted(() => ({
  role: "editor" as "admin" | "editor" | "viewer",
  research: vi.fn(),
}));

const snapshot = {
  id: "11111111-1111-4111-8111-111111111111",
  workspace_id: "workspace-1",
  capture_task_id: "22222222-2222-4222-8222-222222222222",
  target_platform: "douyin" as const,
  source_url: "https://example.com/hot",
  source_host: "example.com",
  page_title: "今日热点榜",
  collected_at: "2026-08-13T08:00:00Z",
  confirmed_at: "2026-08-13T08:01:00Z",
  completeness: "full_page_complete" as const,
  ocr_model_id: "mock-ocr-v1",
  ocr_contract_version: "mock-hotspot-ocr-v1",
  entries: [{ id: "entry-1", position: 1, topic: "AI 新进展", rank: 1, heat: "900万", selected: true }],
};

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/components/workbench/guided-page-header", () => ({
  GuidedPageHeader: () => <h1>热点创作</h1>,
}));
vi.mock("@/components/workbench/workspace-shell", () => ({
  useWorkbenchShellContext: () => ({
    workspace_id: "workspace-1",
    workspace_name: "运营团队",
    member_id: "member-1",
    member_display_name: "运营成员",
    role: state.role,
    accounts: [{ account_id: "account-1", platform: "douyin", name: "抖音科技号" }],
    failed_task_count: 0,
  }),
}));
vi.mock("@/lib/hotspot-api", () => ({
  confirmHotspotCapture: vi.fn(),
  loadHotspotCapture: vi.fn(),
  loadHotspotResearch: vi.fn().mockResolvedValue([]),
  loadHotspotSnapshots: vi.fn(() => Promise.resolve([snapshot])),
  researchHotspot: (...args: unknown[]) => state.research(...args),
  saveHotspotCandidate: vi.fn(),
}));

beforeEach(() => {
  state.role = "editor";
  state.research.mockReset();
  sessionStorage.setItem("workspace_csrf", "csrf-test");
});
afterEach(cleanup);

test("lets an editor start grounded research for the matching platform account", async () => {
  state.research.mockResolvedValue({
    id: "research-1",
    status: "succeeded",
    summary: "已核实公开信息。",
    key_points: ["公开要点"],
    candidates: [{
      topic: "AI 新进展",
      account_fit: "适合科技账号",
      angle: "解释实际影响",
      titles: ["标题一", "标题二", "标题三"],
      copy_draft: "带来源的草稿。",
      caveats: ["人工复核"],
      source_urls: ["https://example.com/source"],
    }],
    saved_content_id: null,
  });
  render(<HotspotReview workspaceId="workspace-1" />);

  const button = await screen.findByRole("button", { name: "联网核实并生成草稿" });
  await userEvent.click(button);

  expect(state.research).toHaveBeenCalledWith(
    "workspace-1",
    snapshot.id,
    "account-1",
    "csrf-test",
  );
  expect(await screen.findByText("已核实公开信息。")).toBeVisible();
  expect(screen.getByRole("link", { name: "https://example.com/source" })).toBeVisible();
});

test("keeps hotspot research read-only for a viewer", async () => {
  state.role = "viewer";
  render(<HotspotReview workspaceId="workspace-1" />);

  expect(await screen.findByText("今日热点榜（1 条）")).toBeVisible();
  expect(screen.queryByRole("button", { name: "联网核实并生成草稿" })).toBeNull();
});
