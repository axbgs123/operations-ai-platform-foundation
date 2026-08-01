import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import type { OperatorPageId } from "./operator-copy-catalog";
import { PageGuide } from "./page-guide";
import { WorkspaceShell } from "./workspace-shell";

const navigationState = vi.hoisted(() => ({
  pathname: "/workspaces/workspace-1/analysis",
  search: "",
  replace: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => navigationState.pathname,
  useRouter: () => ({ replace: navigationState.replace }),
  useSearchParams: () => new URLSearchParams(navigationState.search),
}));

beforeEach(() => {
  localStorage.clear();
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
});

const context = {
  workspace_id: "workspace-1",
  workspace_name: "运营工作区",
  member_id: "member-1",
  member_display_name: "运营成员",
  role: "admin" as const,
  accounts: [],
  failed_task_count: 0,
};

function renderGuidance(
  pageId: OperatorPageId,
  role: "admin" | "editor" | "viewer",
) {
  return render(
    <WorkspaceShell context={{ ...context, role }}>
      <PageGuide pageId={pageId} />
    </WorkspaceShell>,
  );
}

test("always shows the easy purpose and expands persistent guidance", async () => {
  const user = userEvent.setup();
  renderGuidance("analysis", "editor");
  expect(screen.getByText(
    "找出还没分析或分析失败的作品，并查看问题和改进建议。",
  )).toBeVisible();
  expect(screen.getByText("建议先做")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "查看操作说明" }));
  expect(screen.getByRole("region", { name: "分析中心操作说明" })).toBeVisible();
  expect(screen.getByText("怎么使用")).toBeVisible();
  expect(screen.getByText("你会看到什么")).toBeVisible();
  expect(screen.getByText("常见情况")).toBeVisible();
});

test("keeps the purpose when guidance is off", () => {
  localStorage.setItem("operations-ai:page-guidance:member-1", "off");
  renderGuidance("contents", "viewer");
  expect(screen.getByText(
    "集中查看每条作品、发布状态、数据、分析和风险结果。",
  )).toBeVisible();
  expect(screen.queryByText("建议先做")).toBeNull();
  expect(screen.queryByRole("button", { name: "查看操作说明" })).toBeNull();
});

test("switches to the preserved professional purpose", () => {
  localStorage.setItem("operations-ai:copy-mode:member-1", "professional");
  renderGuidance("preflight", "admin");
  expect(screen.getByText(/OCR 的确定性规则与 RAG 辅助判断/)).toBeVisible();
});

test("gives viewers only read or contact guidance", () => {
  renderGuidance("settingsModels", "viewer");
  expect(screen.getByText("联系管理员配置模型和费用上限")).toBeVisible();
  expect(screen.queryByText("配置模型、预算并执行受控验收")).toBeNull();
});
