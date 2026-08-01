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

test("keeps workspace deletion separate and does not offer it to a viewer", () => {
  renderInWorkspace(<WorkspaceSettings workspaceId="ws-1" />, "viewer");

  expect(screen.getByText(
    "管理成员、账号、模型费用限制和工作区安全操作。",
  )).toBeVisible();
  expect(screen.getByText(
    /邀请码只在创建时显示一次。请立即交给对应成员/,
  )).toBeVisible();

  for (const title of [
    "工作区概览",
    "成员与邀请码",
    "平台账号配置",
    "指标、目标与基准",
    "模型配置与预算",
    "保留策略",
    "危险操作",
  ]) {
    expect(screen.getByRole("heading", { name: title })).toBeVisible();
  }
  expect(screen.getByText(/永久删除工作区不会在回收站中进行/)).toBeVisible();
  expect(screen.getByText("只有管理员可以发起工作区删除。")).toBeVisible();
  expect(
    screen.queryByRole("button", { name: /删除工作区/ }),
  ).not.toBeInTheDocument();
});

test("admin deletion starts with impact preview and cannot skip confirmations", () => {
  renderInWorkspace(<WorkspaceSettings role="admin" workspaceId="ws-1" />);

  expect(
    screen.getByRole("button", { name: "第一步：查看删除影响" }),
  ).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "最终确认删除工作区" }),
  ).not.toBeInTheDocument();
});

test("professional mode preserves experimental, Provider, and impact preview terms", () => {
  localStorage.setItem("operations-ai:copy-mode:member-admin", "professional");
  renderInWorkspace(<WorkspaceSettings role="admin" workspaceId="ws-1" />);

  expect(screen.getByText("Catalog experimental")).toBeVisible();
  expect(screen.getByText(/Provider Workspace ID/)).toBeVisible();
  expect(screen.getByText(/影响预览/)).toBeVisible();
});
