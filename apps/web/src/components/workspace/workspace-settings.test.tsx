import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { WorkspaceShell } from "@/components/workbench/workspace-shell";

import { WorkspaceSettings } from "./workspace-settings";

const {
  confirmWorkspaceDeletion,
  readWorkspaceDeletionImpact,
  requestWorkspaceDeletionConfirmation,
} = vi.hoisted(() => ({
  confirmWorkspaceDeletion: vi.fn(),
  readWorkspaceDeletionImpact: vi.fn(),
  requestWorkspaceDeletionConfirmation: vi.fn(),
}));

vi.mock("@/lib/export-api", () => ({
  confirmWorkspaceDeletion,
  readWorkspaceDeletionImpact,
  requestWorkspaceDeletionConfirmation,
}));

const deletionImpact = {
  workspace_id: "ws-1",
  structured_records: 12,
  assets: 3,
  vectors: 5,
  staging_tasks: 1,
  evidence_retained_objects: 2,
  compensation_required_jobs: 1,
  private_knowledge_documents: 1,
  cache_prefixes: ["workspace:ws-1"],
};

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
  confirmWorkspaceDeletion.mockReset();
  readWorkspaceDeletionImpact.mockReset();
  requestWorkspaceDeletionConfirmation.mockReset();
  readWorkspaceDeletionImpact.mockResolvedValue(deletionImpact);
  requestWorkspaceDeletionConfirmation.mockResolvedValue({
    confirmation_token: "one-time-confirmation-secret",
    expires_at: "2026-08-01T08:10:00Z",
    impact: deletionImpact,
  });
  confirmWorkspaceDeletion.mockResolvedValue({
    id: "deletion-1",
    workspace_id: "ws-1",
    status: "queued",
    phase: "queued",
    inventory: {},
    error_code: null,
    completed_at: null,
  });
  sessionStorage.setItem("workspace_csrf", "csrf-token");
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
  expect(screen.queryByRole("link", { name: /管理成员|打开模型/ })).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /删除工作区/ }),
  ).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "创建平台账号" })).toBeNull();
});

test("gives administrators a direct platform-account creation entry", () => {
  renderInWorkspace(<WorkspaceSettings workspaceId="ws-1" />, "admin");

  expect(screen.getByRole("link", { name: "创建平台账号" })).toHaveAttribute(
    "href",
    "/workspaces/ws-1/accounts?action=create",
  );
});

test("keeps the settings creation shortcut admin-only", () => {
  renderInWorkspace(<WorkspaceSettings workspaceId="ws-1" />, "editor");

  expect(screen.queryByRole("link", { name: "创建平台账号" })).toBeNull();
});

test("easy settings translate primary model, retention, and deletion-impact terminology", async () => {
  renderInWorkspace(<WorkspaceSettings role="admin" workspaceId="ws-1" />);

  expect(screen.getByText("尚未进行真实调用验收")).toBeVisible();
  expect(screen.getByText("演示环境不会调用真实模型")).toBeVisible();
  expect(screen.getByText("立即清理")).toBeVisible();
  expect(screen.getByText("按计划清理")).toBeVisible();
  expect(screen.getByText("因审计或关联资料保留")).toBeVisible();
  expect(document.body.textContent).not.toMatch(
    /\b(?:Provider|Embedding|Mock|API Key|not_run|immediate|scheduled|evidence)\b|向量|workbench-2026\.07/,
  );

  fireEvent.click(screen.getByRole("button", { name: "第一步：查看删除影响" }));
  expect(await screen.findByText("用于资料检索的索引")).toBeVisible();
  expect(screen.getByText("自动清理未完成的任务")).toBeVisible();
  expect(document.body.textContent).not.toContain("compensation_required");
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

test("admin deletion requires impact, one-time confirmation, and final mutation", async () => {
  renderInWorkspace(<WorkspaceSettings role="admin" workspaceId="ws-1" />);

  expect(screen.queryByRole("button", {
    name: "第二步：申请短期一次性确认",
  })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", {
    name: "最终确认删除工作区",
  })).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", {
    name: "第一步：查看删除影响",
  }));
  await waitFor(() => expect(readWorkspaceDeletionImpact).toHaveBeenCalledWith("ws-1"));
  expect(screen.getByText("删除前影响检查已加载；尚未申请或执行删除。")).toBeVisible();
  expect(screen.getByRole("button", {
    name: "第二步：申请短期一次性确认",
  })).toBeVisible();

  fireEvent.click(screen.getByRole("button", {
    name: "第二步：申请短期一次性确认",
  }));
  await waitFor(() => expect(requestWorkspaceDeletionConfirmation).toHaveBeenCalledWith(
    "ws-1",
    "csrf-token",
  ));
  expect(screen.getByRole("button", {
    name: "最终确认删除工作区",
  })).toBeVisible();
  expect(document.body.textContent).not.toContain("one-time-confirmation-secret");

  fireEvent.click(screen.getByRole("button", {
    name: "最终确认删除工作区",
  }));
  await waitFor(() => expect(confirmWorkspaceDeletion).toHaveBeenCalledWith(
    "ws-1",
    "one-time-confirmation-secret",
    "csrf-token",
  ));
  expect(document.body.textContent).not.toContain("one-time-confirmation-secret");
});

test("easy and professional deletion fallbacks use their own terminology", async () => {
  readWorkspaceDeletionImpact.mockRejectedValueOnce("synthetic failure");
  const { unmount } = renderInWorkspace(
    <WorkspaceSettings role="admin" workspaceId="ws-1" />,
  );
  fireEvent.click(screen.getByRole("button", {
    name: "第一步：查看删除影响",
  }));
  expect(await screen.findByRole("alert")).toHaveTextContent("删除前影响检查失败");

  unmount();
  localStorage.setItem("operations-ai:copy-mode:member-admin", "professional");
  readWorkspaceDeletionImpact.mockRejectedValueOnce("synthetic failure");
  renderInWorkspace(<WorkspaceSettings role="admin" workspaceId="ws-1" />);
  fireEvent.click(screen.getByRole("button", {
    name: "第一步：查看删除影响",
  }));
  expect(await screen.findByRole("alert")).toHaveTextContent("影响预览失败");
});

test("professional mode preserves experimental, Provider, and impact preview terms", async () => {
  localStorage.setItem("operations-ai:copy-mode:member-admin", "professional");
  renderInWorkspace(<WorkspaceSettings role="admin" workspaceId="ws-1" />);

  expect(screen.getByText("Catalog experimental")).toBeVisible();
  expect(screen.getByText("真实验收 not_run")).toBeVisible();
  expect(screen.getByText("Demo 仅 Mock")).toBeVisible();
  expect(screen.getByText("immediate")).toBeVisible();
  expect(screen.getByText("scheduled")).toBeVisible();
  expect(screen.getByText("evidence")).toBeVisible();
  expect(screen.getByText(/Provider Workspace ID/)).toBeVisible();
  expect(screen.getByText(/影响预览/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", {
    name: "第一步：查看删除影响",
  }));
  expect(await screen.findByText(
    "影响预览已加载；尚未申请或执行删除。",
  )).toBeVisible();
  expect(screen.getByText("向量")).toBeVisible();
  expect(screen.getByText("需补偿任务")).toBeVisible();
});
