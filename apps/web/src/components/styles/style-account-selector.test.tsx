import { cleanup, render as rtlRender, screen } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { WorkspaceShell } from "@/components/workbench/workspace-shell";

import { StyleAccountSelector } from "./style-account-selector";

vi.mock("next/navigation", () => ({
  usePathname: () => "/workspaces/workspace-1/styles",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
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

const accounts = [
  { account_id: "dy-account", platform: "douyin" as const, name: "抖音账号" },
  {
    account_id: "xhs-account",
    platform: "xiaohongshu" as const,
    name: "小红书账号",
  },
];

const shellContext = {
  workspace_id: "workspace-1",
  workspace_name: "运营工作区",
  member_id: "member-admin",
  member_display_name: "运营管理员",
  role: "admin" as const,
  accounts,
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

afterEach(cleanup);

test("explains the easy account-style purpose and keeps viewers read-only", () => {
  renderInWorkspace(
    <StyleAccountSelector accounts={accounts} workspaceId="workspace-1" />,
    "viewer",
  );

  expect(screen.getByText(
    "选择一个账号，查看并维护它常用的标题、文案和封面风格。",
  )).toBeVisible();
  expect(screen.getByText(/优秀内容结构不会自动变成账号风格/)).toBeVisible();
  expect(screen.getByText("建议先做").closest("p")).not.toHaveTextContent(
    /确认候选|确认新版本|添加来源|开始生成/,
  );
});

test("requires one platform account and never merges style profiles", () => {
  renderInWorkspace(
    <StyleAccountSelector
      accounts={accounts}
      workspaceId="workspace-1"
    />,
  );

  expect(screen.getByRole("heading", { name: "账号风格" })).toBeVisible();
  expect(screen.getByText("风格档案始终固定到单个平台账号，不提供全部账号合并视图。")).toBeVisible();
  expect(screen.getByRole("link", { name: "查看抖音账号风格" })).toHaveAttribute(
    "href",
    "/workspaces/workspace-1/styles/dy-account?platform=douyin&account=dy-account",
  );
  expect(screen.getByRole("link", { name: "查看小红书账号风格" })).toHaveAttribute(
    "href",
    "/workspaces/workspace-1/styles/xhs-account?platform=xiaohongshu&account=xhs-account",
  );
  expect(screen.getAllByText("当前版本：进入账号查看")).toHaveLength(2);
});
