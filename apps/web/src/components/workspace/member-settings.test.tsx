import { cleanup, render, screen } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { WorkspaceShell } from "@/components/workbench/workspace-shell";

import { MemberSettings } from "./member-settings";

vi.mock("next/navigation", () => ({
  usePathname: () => "/workspaces/workspace-1/settings/members",
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

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
  return render(ui, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <WorkspaceShell context={{ ...shellContext, role }}>
        {children}
      </WorkspaceShell>
    ),
  });
}

const members = [
  {
    id: "member-1",
    workspace_id: "workspace-1",
    display_name: "合成管理员",
    role: "admin",
    status: "active",
    last_access_at: null,
    last_access_status: "not_recorded",
    invite_status: "redeemed",
  },
] as const;

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

test("admin sees secret-free member status while access time remains honest", () => {
  renderInWorkspace(
    <MemberSettings
      fixture={[...members]}
      role="admin"
      workspaceId="workspace-1"
    />,
  );

  expect(screen.getByText(
    "给每个人创建独立邀请码、设置权限，并在成员离开时单独撤销。",
  )).toBeVisible();
  expect(screen.getByText(
    "邀请码只在创建时显示一次。请立即交给对应成员，不要发到公开群或截图保存到公共位置。",
  )).toBeVisible();
  expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  expect(screen.getByText("合成管理员")).toBeVisible();
  expect(screen.getByText(/最后访问：当前认证合同未记录/)).toBeVisible();
  expect(screen.getByText(/邀请码：已兑换/)).toBeVisible();
  expect(
    screen.getByRole("button", { name: "生成独立邀请码" }),
  ).toBeVisible();
  expect(document.body.textContent).not.toMatch(/hash|token|session/i);
});

test("editor and viewer never receive member mutation controls", () => {
  const { rerender } = renderInWorkspace(
    <MemberSettings role="editor" workspaceId="workspace-1" />,
    "editor",
  );
  expect(screen.getByText("当前角色不可管理成员或邀请码。")).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "生成独立邀请码" }),
  ).not.toBeInTheDocument();

  rerender(<MemberSettings role="viewer" workspaceId="workspace-1" />);
  expect(
    screen.queryByRole("button", { name: "生成独立邀请码" }),
  ).not.toBeInTheDocument();
});
