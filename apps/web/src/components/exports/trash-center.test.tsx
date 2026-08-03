import { cleanup, render, screen } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { WorkspaceShell } from "@/components/workbench/workspace-shell";

import { TrashCenter, type TrashFixture } from "./trash-center";

vi.mock("next/navigation", () => ({
  usePathname: () => "/workspaces/ws-1/trash",
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

const fixture: TrashFixture = {
  policy: {
    strategy: "evidence",
    version: 3,
    retention_seconds: 604800,
    effective_at: "2026-07-29T08:00:00Z",
  },
  items: [
    {
      id: "trash-1",
      resource_id: "content-1",
      resource_type: "content",
      title: "合成内容安全摘要",
      platform: "douyin",
      account_name: "抖音合成账号",
      deleted_by: "member-1",
      deleted_at: "2026-07-29T08:00:00Z",
      scheduled_purge_at: "2099-07-29T08:00:00Z",
      deletion_reason: "用户整理",
      status: "recoverable",
      restored_at: null,
      evidence_hold_reason: "关联风控扫描证据",
    },
    {
      id: "trash-2",
      resource_id: "content-2",
      resource_type: "content",
      title: "已恢复内容",
      platform: "xiaohongshu",
      account_name: "小红书合成账号",
      deleted_by: "member-1",
      deleted_at: "2026-07-28T08:00:00Z",
      scheduled_purge_at: "2026-07-29T08:00:00Z",
      deletion_reason: null,
      status: "restored",
      restored_at: "2026-07-29T07:00:00Z",
      evidence_hold_reason: null,
    },
  ],
};

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

test("shows content lifecycle and separates workspace deletion", () => {
  const easy = renderInWorkspace(
    <TrashCenter
      evaluatedAt="2026-07-30T00:00:00Z"
      fixture={{
        ...fixture,
        policy: { ...fixture.policy, retention_seconds: null },
      } as unknown as TrashFixture}
      role="admin"
      workspaceId="ws-1"
    />,
  );

  expect(screen.getByText(
    "恢复还在保留期内的内容；永久删除工作区要到设置中单独操作。",
  )).toBeVisible();
  expect(screen.getByText(
    "这里只恢复仍在保留期内的内容。永久删除整个工作区需要到设置中查看影响并再次确认。",
  )).toBeVisible();
  expect(screen.getByText("可恢复")).toBeVisible();
  expect(screen.getByText("已恢复")).toBeVisible();
  expect(screen.getByText(
    "因审计或关联资料要求而保留，暂时不能删除：关联风控扫描证据",
  )).toBeVisible();
  expect(screen.getByText("关联资料决定")).toBeVisible();
  expect(easy.container.textContent).not.toMatch(/\bEvidence\b|门禁|向量/);
  expect(screen.queryByRole("button", { name: "删除工作区" })).not.toBeInTheDocument();
});

test("viewer receives no restore or purge operation", () => {
  renderInWorkspace(
    <TrashCenter
      evaluatedAt="2026-07-30T00:00:00Z"
      fixture={{
        ...fixture,
        policy: { ...fixture.policy, retention_seconds: null },
      } as unknown as TrashFixture}
      role="viewer"
      workspaceId="ws-1"
    />,
    "viewer",
  );

  expect(screen.queryByRole("button", { name: "恢复内容" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "最终删除" })).not.toBeInTheDocument();
});

test("professional mode preserves retention evidence terminology", () => {
  localStorage.setItem("operations-ai:copy-mode:member-admin", "professional");
  renderInWorkspace(
    <TrashCenter
      evaluatedAt="2026-07-30T00:00:00Z"
      fixture={{
        ...fixture,
        policy: { ...fixture.policy, retention_seconds: null },
      } as unknown as TrashFixture}
      role="admin"
      workspaceId="ws-1"
    />,
  );

  expect(screen.getByText("Evidence 保留：关联风控扫描证据")).toBeVisible();
  expect(screen.getByText("Evidence 决定")).toBeVisible();
});
