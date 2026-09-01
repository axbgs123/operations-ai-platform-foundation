import { cleanup, render, screen } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { WorkspaceShell } from "@/components/workbench/workspace-shell";

import { WorkspaceSettings } from "./workspace-settings";

vi.mock("next/navigation", () => ({
  usePathname: () => "/workspaces/ws-1/settings",
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

const shellContext = {
  workspace_id: "ws-1",
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
  return render(ui, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <WorkspaceShell context={{ ...shellContext, role }}>
        {children}
      </WorkspaceShell>
    ),
  });
}

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

afterEach(cleanup);

test("shows only the four operator-facing settings areas", () => {
  renderInWorkspace(<WorkspaceSettings workspaceId="ws-1" />, "viewer");

  for (const title of [
    "工作区概览",
    "成员与邀请码",
    "平台账号",
    "AI 模型连接",
  ]) {
    expect(screen.getByRole("heading", { name: title })).toBeVisible();
  }
  for (const removed of ["保留策略", "危险操作", "模型配置与预算"]) {
    expect(screen.queryByText(removed)).not.toBeInTheDocument();
  }
  expect(screen.getByText("当前为只读权限")).toBeVisible();
  expect(screen.getByText("联系管理员配置模型")).toBeVisible();
  expect(screen.queryByRole("link", { name: "创建平台账号" })).toBeNull();
});

test("gives administrators direct account and model entries", () => {
  renderInWorkspace(<WorkspaceSettings workspaceId="ws-1" />, "admin");

  expect(screen.getByRole("link", { name: "创建平台账号" })).toHaveAttribute(
    "href",
    "/workspaces/ws-1/accounts?action=create",
  );
  expect(screen.getByRole("link", { name: "打开模型连接" })).toHaveAttribute(
    "href",
    "/workspaces/ws-1/settings/models",
  );
  expect(screen.getByText("还没有添加抖音或小红书账号。")).toBeVisible();
});

test("keeps account creation admin-only", () => {
  renderInWorkspace(<WorkspaceSettings workspaceId="ws-1" />, "editor");

  expect(screen.queryByRole("link", { name: "创建平台账号" })).toBeNull();
  expect(screen.getByRole("link", { name: "打开模型连接" })).toBeVisible();
});
