import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import {
  ALL_WORKBENCH_MODULE_LABELS,
  visibleNavigationItems,
} from "./navigation";
import { SidebarNav } from "./sidebar-nav";
import {
  buildWorkspaceHref,
  parseWorkbenchScope,
  readSidebarPreference,
  sanitizeReturnTo,
  toWorkbenchApiScope,
  writeSidebarPreference,
} from "./scope-query";
import {
  WorkspaceShell,
  WorkspaceShellLoader,
} from "./workspace-shell";


const navigationState = vi.hoisted(() => ({
  pathname: "/workspaces/workspace-1/contents",
  search: "",
  replace: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => navigationState.pathname,
  useRouter: () => ({ replace: navigationState.replace }),
  useSearchParams: () => new URLSearchParams(navigationState.search),
}));

const accounts = [
  {
    account_id: "dy-account",
    name: "抖音合成账号",
    platform: "douyin" as const,
  },
  {
    account_id: "xhs-account",
    name: "小红书合成账号",
    platform: "xiaohongshu" as const,
  },
];

const context = {
  workspace_id: "workspace-1",
  workspace_name: "合成运营工作区",
  member_id: "member-admin",
  member_display_name: "运营管理员",
  role: "admin" as const,
  accounts,
  failed_task_count: 2,
};

function setMobileViewport(matches: boolean) {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
    writable: true,
  });
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
    status,
  });
}

beforeEach(() => {
  navigationState.pathname = "/workspaces/workspace-1/contents";
  navigationState.search = "";
  navigationState.replace.mockReset();
  localStorage.clear();
  setMobileViewport(false);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("canonical navigation and roles", () => {
  test("gives every formal module exactly one grouped entry", () => {
    expect(ALL_WORKBENCH_MODULE_LABELS).toEqual([
      "工作台总览",
      "账号仪表盘",
      "栏目与活动",
      "内容库",
      "数据导入",
      "分析中心",
      "爆款素材库",
      "账号风格",
      "事实资料",
      "生成中心",
      "发布前检查",
      "风控知识库",
      "导出与备份",
      "回收站",
      "后台任务",
      "工作区设置",
    ]);
    expect(new Set(ALL_WORKBENCH_MODULE_LABELS)).toHaveLength(16);
  });

  test("applies the approved admin editor and viewer navigation matrix", () => {
    expect(visibleNavigationItems("admin").map((item) => item.label)).toEqual(
      ALL_WORKBENCH_MODULE_LABELS,
    );
    expect(visibleNavigationItems("editor").map((item) => item.label)).toEqual([
      "工作台总览",
      "账号仪表盘",
      "栏目与活动",
      "内容库",
      "数据导入",
      "分析中心",
      "爆款素材库",
      "账号风格",
      "事实资料",
      "生成中心",
      "发布前检查",
      "导出与备份",
      "后台任务",
    ]);
    expect(visibleNavigationItems("viewer").map((item) => item.label)).toEqual([
      "工作台总览",
      "账号仪表盘",
      "内容库",
      "分析中心",
      "爆款素材库",
      "账号风格",
      "事实资料",
      "生成中心",
      "发布前检查",
    ]);
  });

  test("marks only the unique primary entry for the current route", () => {
    render(
      <SidebarNav
        collapsed={false}
        onNavigate={() => undefined}
        pathname="/workspaces/workspace-1/settings/jobs"
        role="admin"
        workspaceId="workspace-1"
      />,
    );

    expect(screen.getByRole("link", { name: "后台任务" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(
      screen.getByRole("link", { name: "工作区设置" }),
    ).not.toHaveAttribute("aria-current");
  });
});

describe("workspace scope and safe returns", () => {
  test("restores only compatible platform and account scope", () => {
    expect(
      parseWorkbenchScope(
        new URLSearchParams("platform=douyin&account=dy-account"),
        accounts,
      ),
    ).toEqual({ platform: "douyin", accountId: "dy-account" });
    expect(
      parseWorkbenchScope(
        new URLSearchParams("platform=douyin&account=xhs-account"),
        accounts,
      ),
    ).toEqual({ platform: "douyin" });
    expect(
      parseWorkbenchScope(
        new URLSearchParams("platform=weibo&account=dy-account"),
        accounts,
      ),
    ).toEqual({});
    expect(
      parseWorkbenchScope(
        new URLSearchParams("account=xhs-account"),
        accounts,
      ),
    ).toEqual({ platform: "xiaohongshu", accountId: "xhs-account" });
    expect(
      parseWorkbenchScope(
        new URLSearchParams("platform=douyin&account=old-workspace-account"),
        accounts,
      ),
    ).toEqual({ platform: "douyin" });
  });

  test("maps the Web account query to the generated API account_id contract", () => {
    const scope = { platform: "douyin" as const, accountId: "dy-account" };

    expect(buildWorkspaceHref("workspace-1", "/contents", scope)).toBe(
      "/workspaces/workspace-1/contents?platform=douyin&account=dy-account",
    );
    expect(toWorkbenchApiScope(scope)).toEqual({
      platform: "douyin",
      account_id: "dy-account",
    });
  });

  test.each([
    "https://attacker.example/path",
    "//attacker.example/path",
    "%2F%2Fattacker.example/path",
    "%252F%252Fattacker.example/path",
    "/workspaces/workspace-2/contents",
    "/workspaces/workspace-1/../workspace-2/contents",
    "/workspaces%2Fworkspace-2%2Fcontents",
    "\\\\attacker.example\\path",
  ])("rejects unsafe returnTo value %s", (value) => {
    expect(sanitizeReturnTo("workspace-1", value)).toBeUndefined();
  });

  test("keeps only an allowed route in returnTo", () => {
    const returnTo =
      "/workspaces/workspace-1/analysis?platform=douyin&account=dy-account";

    expect(sanitizeReturnTo("workspace-1", returnTo)).toBe(returnTo);
    expect(
      buildWorkspaceHref(
        "workspace-1",
        "/contents/content-1",
        { platform: "douyin", accountId: "dy-account" },
        returnTo,
      ),
    ).toBe(
      "/workspaces/workspace-1/contents/content-1?platform=douyin&account=dy-account&returnTo=%2Fworkspaces%2Fworkspace-1%2Fanalysis%3Fplatform%3Ddouyin%26account%3Ddy-account",
    );
  });
});

describe("workspace shell behavior", () => {
  test("stores only an isolated expanded or collapsed member preference", () => {
    writeSidebarPreference(localStorage, "member-admin", "collapsed");
    writeSidebarPreference(localStorage, "member-viewer", "expanded");
    localStorage.setItem("operations-ai:sidebar:invalid", "PRIVATE_DATA");

    expect(readSidebarPreference(localStorage, "member-admin")).toBe(
      "collapsed",
    );
    expect(readSidebarPreference(localStorage, "member-viewer")).toBe(
      "expanded",
    );
    expect(readSidebarPreference(localStorage, "invalid")).toBe("expanded");
    expect(localStorage.getItem("operations-ai:sidebar:member-admin")).toBe(
      "collapsed",
    );
  });

  test("renders breadcrumbs scope identity help task alert and main landmark", () => {
    render(
      <WorkspaceShell context={context}>
        <p>页面业务内容</p>
      </WorkspaceShell>,
    );

    const breadcrumb = screen.getByRole("navigation", { name: "面包屑" });
    expect(breadcrumb).toHaveTextContent("合成运营工作区");
    expect(breadcrumb).toHaveTextContent("内容库");
    expect(screen.getByRole("combobox", { name: "平台范围" })).toBeVisible();
    expect(screen.getByRole("combobox", { name: "账号范围" })).toBeVisible();
    expect(screen.getByText("运营管理员")).toBeVisible();
    expect(screen.getByText("管理员")).toBeVisible();
    expect(screen.getByRole("link", { name: "帮助" })).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("2 个失败任务");
    expect(screen.getByRole("link", { name: "跳转到主内容" })).toHaveAttribute(
      "href",
      "#main-content",
    );
    expect(screen.getByRole("main")).toHaveAttribute("id", "main-content");
  });

  test("persists the desktop width preference under the current member only", async () => {
    const user = userEvent.setup();
    render(
      <WorkspaceShell context={context}>
        <p>页面业务内容</p>
      </WorkspaceShell>,
    );

    expect(screen.getByRole("complementary")).toHaveAttribute(
      "data-width",
      "240",
    );
    await user.click(screen.getByRole("button", { name: "折叠侧边栏" }));
    expect(screen.getByRole("complementary")).toHaveAttribute(
      "data-width",
      "72",
    );
    expect(localStorage.getItem("operations-ai:sidebar:member-admin")).toBe(
      "collapsed",
    );
    expect(localStorage).toHaveLength(1);
  });

  test("opens a focus-managed inert-background drawer at 390px", async () => {
    setMobileViewport(true);
    const user = userEvent.setup();
    render(
      <WorkspaceShell context={context}>
        <button type="button">背景操作</button>
      </WorkspaceShell>,
    );

    const trigger = screen.getByRole("button", { name: "打开主导航" });
    await user.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "主导航" });
    expect(dialog).toBeVisible();
    expect(
      screen.getByTestId("workspace-shell-background"),
    ).toHaveAttribute("inert");
    expect(screen.getByRole("button", { name: "关闭主导航" })).toHaveFocus();

    await user.tab();
    expect(dialog).toContainElement(document.activeElement as HTMLElement);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "主导航" })).toBeNull();
    expect(trigger).toHaveFocus();
  });

  test("closes the mobile drawer after the route changes", async () => {
    setMobileViewport(true);
    const user = userEvent.setup();
    const { rerender } = render(
      <WorkspaceShell context={context}>
        <p>内容库</p>
      </WorkspaceShell>,
    );
    await user.click(screen.getByRole("button", { name: "打开主导航" }));
    expect(screen.getByRole("dialog", { name: "主导航" })).toBeVisible();

    navigationState.pathname = "/workspaces/workspace-1/analysis";
    rerender(
      <WorkspaceShell context={context}>
        <p>分析中心</p>
      </WorkspaceShell>,
    );
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "主导航" })).toBeNull(),
    );
  });
});

describe("workbench context loading", () => {
  test("shows a safe loading state and then the private shell", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(context)));

    render(
      <WorkspaceShellLoader workspaceId="workspace-1">
        <p>私有页面</p>
      </WorkspaceShellLoader>,
    );

    expect(
      screen.getByRole("status", { name: "正在加载工作区" }),
    ).toBeVisible();
    expect(await screen.findByText("私有页面")).toBeVisible();
  });

  test("does not render private children when the session has expired", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ detail: "invalid session" }, 401)),
    );

    render(
      <WorkspaceShellLoader workspaceId="workspace-1">
        <p>不得泄露的私有页面</p>
      </WorkspaceShellLoader>,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("会话已失效");
    expect(
      screen.getByRole("link", { name: "重新进入工作区" }),
    ).toHaveAttribute("href", "/enter");
    expect(screen.queryByText("不得泄露的私有页面")).toBeNull();
  });

  test("shows a retryable safe error without exposing API details", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(
          jsonResponse({ detail: "database connection secret" }, 500),
        )
        .mockResolvedValueOnce(jsonResponse(context)),
    );
    const user = userEvent.setup();

    render(
      <WorkspaceShellLoader workspaceId="workspace-1">
        <p>恢复后的页面</p>
      </WorkspaceShellLoader>,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "工作区加载失败",
    );
    expect(screen.getByRole("alert")).not.toHaveTextContent(
      "database connection secret",
    );
    await user.click(screen.getByRole("button", { name: "重新加载" }));
    expect(await screen.findByText("恢复后的页面")).toBeVisible();
  });
});
