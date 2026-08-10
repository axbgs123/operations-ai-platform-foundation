import { cleanup, render, screen } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { WorkspaceShell } from "@/components/workbench/workspace-shell";
import type { WorkbenchOverviewData } from "@/lib/workbench-api";

import {
  AccountList,
  AccountListPage,
  filterAccountsByScope,
} from "./account-list";

const navigationState = vi.hoisted(() => ({
  pathname: "/workspaces/workspace-1/accounts",
  search: "",
  replace: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => navigationState.pathname,
  useRouter: () => ({ replace: navigationState.replace }),
  useSearchParams: () => new URLSearchParams(navigationState.search),
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

const accounts = [
  {
    account_id: "account-1",
    platform: "douyin",
    name: "抖音视频账号",
    content_type_counts: { video: 8, image_text: 0 },
    completeness: {
      score: 0.8,
      missing_items: [],
      version: "profile-completeness-v1",
    },
    pending_analysis_count: 2,
    open_risk_count: 0,
    has_current_week_closed_loop: false,
    confirmed_snapshot_count: 8,
    latest_maturity_bucket: "24h",
  },
  {
    account_id: "account-2",
    platform: "xiaohongshu",
    name: "小红书图文账号",
    content_type_counts: { video: 0, image_text: 5 },
    completeness: {
      score: 0.6,
      missing_items: ["confirmed_snapshot"],
      version: "profile-completeness-v1",
    },
    pending_analysis_count: 1,
    open_risk_count: 1,
    has_current_week_closed_loop: false,
    confirmed_snapshot_count: 0,
    latest_maturity_bucket: null,
  },
] as WorkbenchOverviewData["accounts"];

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
  vi.unstubAllGlobals();
});

test("shows the easy account purpose and read-only next action to viewers", () => {
  vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));
  renderInWorkspace(
    <AccountListPage workspaceId="workspace-1" />,
    "viewer",
  );

  expect(screen.getByText(
    "分账号查看运营状态；抖音和小红书的数据不会混在一起计算。",
  )).toBeVisible();
  expect(screen.getByText("打开一个账号查看表现")).toBeVisible();
  expect(
    screen.queryByRole("button", { name: /新建|配置|保存/ }),
  ).not.toBeInTheDocument();
});

test("shows separate platform account cards and stable scoped links", () => {
  render(<AccountList accounts={accounts} workspaceId="workspace-1" />);

  expect(screen.getByText("视频 8 条")).toBeVisible();
  expect(screen.getByText("图文 5 条")).toBeVisible();
  expect(screen.getByText("24h · 8 条已确认快照")).toBeVisible();
  expect(screen.getByText("尚无已确认快照")).toBeVisible();
  expect(screen.getByRole("link", { name: "查看抖音视频账号" })).toHaveAttribute(
    "href",
    "/workspaces/workspace-1/accounts/account-1?platform=douyin&account=account-1",
  );
});

test("uses a single-column card layout at 390px without dropping critical labels", () => {
  render(<AccountList accounts={accounts} workspaceId="workspace-1" />);

  const list = screen.getByRole("list", { name: "账号仪表盘列表" });
  expect(list).toHaveClass("grid-cols-1");
  expect(screen.getAllByText(/数据完整度/)).toHaveLength(2);
  expect(screen.getAllByText(/风险状态/)).toHaveLength(2);
});

test("filters account cards by compatible URL platform and account scope", () => {
  expect(filterAccountsByScope(accounts, "douyin", null).map((item) => item.account_id)).toEqual([
    "account-1",
  ]);
  expect(filterAccountsByScope(accounts, "xiaohongshu", "account-1")).toEqual([]);
  expect(filterAccountsByScope(accounts, "xiaohongshu", "account-2")).toEqual([
    accounts[1],
  ]);
});

test("gives editors a direct account-page creation entry and opens one shared form", () => {
  navigationState.search = "action=create";
  vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));

  renderInWorkspace(<AccountListPage workspaceId="workspace-1" />, "editor");

  expect(screen.getByRole("link", { name: "创建平台账号" })).toHaveAttribute(
    "href",
    "/workspaces/workspace-1/accounts?action=create",
  );
  expect(screen.getByRole("heading", { name: "创建平台账号" })).toBeVisible();
  expect(screen.getByRole("button", { name: "创建账号" })).toBeVisible();
});

test("keeps account creation actions hidden from viewers", () => {
  navigationState.search = "action=create";
  vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));

  renderInWorkspace(<AccountListPage workspaceId="workspace-1" />, "viewer");

  expect(screen.queryByRole("link", { name: "创建平台账号" })).toBeNull();
  expect(screen.queryByRole("button", { name: "创建账号" })).toBeNull();
});
