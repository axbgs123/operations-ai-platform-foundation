import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import userEvent from "@testing-library/user-event";

import { WorkspaceShell } from "@/components/workbench/workspace-shell";
import type { ImportHistoryData } from "@/lib/import-api";

import { ImportCenter, ImportCenterPage } from "./import-center";

const loadImportHistory = vi.hoisted(() => vi.fn());

const navigationState = vi.hoisted(() => ({
  pathname: "/workspaces/workspace-1/imports",
  search: "",
  replace: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => navigationState.pathname,
  useRouter: () => ({ replace: navigationState.replace }),
  useSearchParams: () => new URLSearchParams(navigationState.search),
}));

vi.mock("@/lib/import-api", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/import-api")>(),
  loadImportHistory,
}));

const shellContext = {
  workspace_id: "workspace-1",
  workspace_name: "运营工作区",
  member_id: "member-admin",
  member_display_name: "运营管理员",
  role: "admin" as const,
  accounts: [
    { account_id: "dy-1", platform: "douyin" as const, name: "抖音账号" },
    {
      account_id: "xhs-1",
      platform: "xiaohongshu" as const,
      name: "小红书账号",
    },
  ],
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
  loadImportHistory.mockReset();
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

const accounts = [
  { account_id: "dy-1", platform: "douyin", name: "抖音账号" },
  { account_id: "xhs-1", platform: "xiaohongshu", name: "小红书账号" },
] as const;

const history = {
  items: [
    {
      id: "batch-1",
      method: "screenshot",
      platform: "douyin",
      account_id: "dy-1",
      account_name: "抖音账号",
      status: "waiting_confirmation",
      counts: {
        new: 1,
        update: 0,
        suspected_duplicate: 0,
        failed: 1,
      },
      created_at: "2026-07-30T09:00:00+08:00",
      confirmed_at: null,
      operator_name: "编辑成员",
      safe_error_code: "LOW_CONFIDENCE_FIELDS",
      next_action: "review",
    },
  ],
  page: 1,
  page_size: 20,
  total: 1,
  pages: 1,
  platform: "douyin",
  account_id: "dy-1",
} as ImportHistoryData;

test("exposes four methods through one staged preview and confirmation flow", () => {
  const onMethodChange = vi.fn();
  renderInWorkspace(
    <ImportCenter
      accountId="dy-1"
      accounts={[...accounts]}
      history={history}
      method={undefined}
      onMethodChange={onMethodChange}
      onScopeChange={vi.fn()}
      platform="douyin"
      role="editor"
      workspaceId="workspace-1"
    />,
    "editor",
  );

  expect(screen.getByText(
    "把作品和发布后的运营数据录入系统；确认前不会写入正式记录。",
  )).toBeVisible();
  for (const label of [
    "手动录入",
    "Excel / CSV",
    "截图识别",
    "Capture Extension",
  ]) {
    expect(screen.getByRole("button", { name: label })).toBeVisible();
  }
  expect(screen.getByLabelText("统一导入流程")).toHaveTextContent("选择来源");
  expect(screen.getByLabelText("统一导入流程")).toHaveTextContent("上传/采集");
  expect(screen.getByLabelText("统一导入流程")).toHaveTextContent("暂存预览");
  expect(screen.getByLabelText("统一导入流程")).toHaveTextContent("修正");
  expect(screen.getByLabelText("统一导入流程")).toHaveTextContent("确认入库");
  fireEvent.click(screen.getByRole("button", { name: "Excel / CSV" }));
  expect(onMethodChange).toHaveBeenCalledWith("tabular");
});

test("keeps history safe and makes complex mapping desktop-only on mobile", () => {
  renderInWorkspace(
    <ImportCenter
      accountId="dy-1"
      accounts={[...accounts]}
      history={history}
      method="tabular"
      onMethodChange={vi.fn()}
      onScopeChange={vi.fn()}
      platform="douyin"
      role="editor"
      workspaceId="workspace-1"
    />,
    "editor",
  );

  expect(screen.getByText("此操作需要电脑端")).toBeVisible();
  expect(screen.getByRole("table", { name: "导入历史桌面列表" })).toBeVisible();
  expect(screen.getByRole("list", { name: "导入历史移动卡片" })).toHaveClass(
    "md:hidden",
  );
  expect(screen.getByText("LOW_CONFIDENCE_FIELDS")).toBeVisible();
  expect(document.body.textContent).not.toMatch(
    /Authorization|Bearer|Cookie|raw_data|截图正文/,
  );
});

test("viewer sees history but no upload, edit, or confirmation controls", () => {
  renderInWorkspace(
    <ImportCenter
      accountId="dy-1"
      accounts={[...accounts]}
      history={history}
      method={undefined}
      onMethodChange={vi.fn()}
      onScopeChange={vi.fn()}
      platform="douyin"
      role="viewer"
      workspaceId="workspace-1"
    />,
    "viewer",
  );

  expect(screen.getByText("查看最近导入记录")).toBeVisible();
  expect(screen.getByText("当前操作不可用")).toBeVisible();
  expect(screen.getByText("导入历史")).toBeVisible();
  expect(screen.queryByRole("button", { name: "手动录入" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /确认/ })).not.toBeInTheDocument();
  expect(screen.queryByLabelText("CSV 或 Excel 文件")).not.toBeInTheDocument();
  expect(screen.queryByText("继续确认")).not.toBeInTheDocument();
  expect(screen.getAllByText(
    "查看等待确认的导入记录；需要确认时请联系管理员或编辑者。",
  ).length).toBeGreaterThan(0);
});

test("shows the shared extension connection entry in the extension import method", () => {
  renderInWorkspace(
    <ImportCenter
      accountId="dy-1"
      accounts={[...accounts]}
      history={history}
      method="extension"
      onMethodChange={vi.fn()}
      onScopeChange={vi.fn()}
      platform="douyin"
      role="editor"
      workspaceId="workspace-1"
    />,
    "editor",
  );

  const extensionSection = screen.getByRole("heading", {
    name: "连接 Capture Extension",
  }).closest("section");
  expect(extensionSection).not.toBeNull();
  expect(within(extensionSection!).getByRole("button", { name: "连接扩展" })).toBeVisible();
  expect(screen.queryByText("请在扩展弹窗查看当前短期绑定")).toBeNull();
});

test("opens the shared pairing dialog from the extension import entry", async () => {
  const user = userEvent.setup();
  renderInWorkspace(
    <ImportCenter
      accountId="dy-1"
      accounts={[...accounts]}
      history={history}
      method="extension"
      onMethodChange={vi.fn()}
      onScopeChange={vi.fn()}
      platform="douyin"
      role="editor"
      workspaceId="workspace-1"
    />,
    "editor",
  );

  const extensionSection = screen.getByRole("heading", {
    name: "连接 Capture Extension",
  }).closest("section");
  expect(extensionSection).not.toBeNull();
  await user.click(within(extensionSection!).getByRole("button", { name: "连接扩展" }));

  expect(screen.getByRole("dialog", { name: "连接浏览器扩展" })).toBeVisible();
});

test("keeps extension connection guidance read-only for a viewer", () => {
  renderInWorkspace(
    <ImportCenter
      accountId="dy-1"
      accounts={[...accounts]}
      history={history}
      method="extension"
      onMethodChange={vi.fn()}
      onScopeChange={vi.fn()}
      platform="douyin"
      role="viewer"
      workspaceId="workspace-1"
    />,
    "viewer",
  );

  const extensionSection = screen.getByRole("heading", {
    name: "连接 Capture Extension",
  }).closest("section");
  expect(extensionSection).not.toBeNull();
  expect(within(extensionSection!).getByText(
    "查看者只能查看扩展连接说明。请联系管理员或编辑者生成连接码。",
  )).toBeVisible();
  expect(within(extensionSection!).queryByRole("button", { name: "连接扩展" })).toBeNull();
});

test("shows read/contact-only review guidance to a Viewer in professional mode", () => {
  localStorage.setItem("operations-ai:copy-mode:member-admin", "professional");
  renderInWorkspace(
    <ImportCenter
      accountId="dy-1"
      accounts={[...accounts]}
      history={history}
      method={undefined}
      onMethodChange={vi.fn()}
      onScopeChange={vi.fn()}
      platform="douyin"
      role="viewer"
      workspaceId="workspace-1"
    />,
    "viewer",
  );

  expect(screen.getAllByText(
    "Viewer 只读查看等待确认的导入记录；继续确认需要 Admin 或 Editor。",
  )[0]).toBeVisible();
  expect(screen.queryByText("Viewer 只读继续确认")).not.toBeInTheDocument();
});

test("keeps one title, purpose, and guide while import history loads or fails", async () => {
  loadImportHistory.mockImplementationOnce(() => new Promise(() => undefined));
  const { unmount } = renderInWorkspace(
    <ImportCenterPage workspaceId="workspace-1" />,
  );
  expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  expect(screen.getByRole("heading", { level: 1, name: "数据导入" })).toBeVisible();
  expect(screen.getByText(
    "把作品和发布后的运营数据录入系统；确认前不会写入正式记录。",
  )).toBeVisible();
  expect(screen.getByRole("button", { name: "查看操作说明" })).toBeVisible();

  unmount();
  localStorage.setItem("operations-ai:copy-mode:member-admin", "professional");
  localStorage.setItem("operations-ai:page-guidance:member-admin", "off");
  loadImportHistory.mockRejectedValueOnce(new Error("PRIVATE_PROVIDER_ERROR"));
  renderInWorkspace(<ImportCenterPage workspaceId="workspace-1" />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "导入历史暂时无法读取；已保存数据和当前筛选不会受到影响。",
  );
  expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  expect(screen.getByText(
    "四种方式共享暂存、预览、修正和人工确认边界；确认前不会写入正式内容或快照。",
  )).toBeVisible();
  expect(screen.queryByText("建议先做")).not.toBeInTheDocument();
  expect(document.body).not.toHaveTextContent("PRIVATE_PROVIDER_ERROR");
});

test("clears an account when the selected platform is incompatible", () => {
  const onScopeChange = vi.fn();
  renderInWorkspace(
    <ImportCenter
      accountId="dy-1"
      accounts={[...accounts]}
      history={history}
      method={undefined}
      onMethodChange={vi.fn()}
      onScopeChange={onScopeChange}
      platform="douyin"
      role="admin"
      workspaceId="workspace-1"
    />,
    "admin",
  );

  fireEvent.change(screen.getByLabelText("导入平台"), {
    target: { value: "xiaohongshu" },
  });
  expect(onScopeChange).toHaveBeenCalledWith({
    platform: "xiaohongshu",
    accountId: undefined,
  });
});

test("explains how to choose a safe import scope in easy mode", () => {
  renderInWorkspace(
    <ImportCenter
      accounts={[...accounts]}
      history={history}
      method="manual"
      onMethodChange={vi.fn()}
      onScopeChange={vi.fn()}
      role="editor"
      workspaceId="workspace-1"
    />,
    "editor",
  );

  expect(screen.getByText(
    "先选择抖音或小红书，再选择对应账号；两个平台的数据不会混在一起。",
  )).toBeVisible();
});
