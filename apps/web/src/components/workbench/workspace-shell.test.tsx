import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import {
  ALL_WORKBENCH_MODULE_LABELS,
  activeNavigationCategory,
  defaultNavigationItem,
  visibleNavigationItems,
  visibleNavigationCategories,
  WORKBENCH_NAV_CATEGORIES,
} from "./navigation";
import {
  clearNavigationPreferences,
  readRecentNavigationPath,
  writeRecentNavigationPath,
} from "./navigation-preference";
import { SidebarNav } from "./sidebar-nav";
import {
  buildWorkspaceHref,
  parseWorkbenchScope,
  readSidebarPreference,
  sanitizeReturnTo,
  scopeForWorkspacePath,
  toWorkbenchApiScope,
  writeSidebarPreference,
} from "./scope-query";
import {
  WorkspaceShell,
  WorkspaceShellLoader,
  useWorkbenchShellContext,
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
  test("maps every formal module exactly once into five stable categories", () => {
    expect(WORKBENCH_NAV_CATEGORIES.map((category) => category.id)).toEqual([
      "overview",
      "operations",
      "creation",
      "assets",
      "management",
    ]);
    expect(ALL_WORKBENCH_MODULE_LABELS).toEqual([
      "工作台总览",
      "内容库",
      "数据导入",
      "分析中心",
      "账号仪表盘",
      "栏目与活动",
      "运营智能体",
      "生成中心",
      "发布前检查",
      "爆款素材库",
      "账号风格",
      "事实资料",
      "导出与备份",
      "后台任务",
      "风控知识库",
      "回收站",
      "工作区设置",
    ]);
    expect(new Set(ALL_WORKBENCH_MODULE_LABELS)).toHaveLength(17);
  });

  test("applies the approved admin editor and viewer navigation matrix", () => {
    expect(visibleNavigationCategories("admin").map(({ id }) => id)).toEqual([
      "overview",
      "operations",
      "creation",
      "assets",
      "management",
    ]);
    expect(visibleNavigationCategories("editor").map(({ id }) => id)).toEqual([
      "overview",
      "operations",
      "creation",
      "assets",
      "management",
    ]);
    expect(visibleNavigationCategories("viewer").map(({ id }) => id)).toEqual([
      "overview",
      "operations",
      "creation",
      "assets",
    ]);
    expect(visibleNavigationItems("admin").map((item) => item.label)).toEqual(
      ALL_WORKBENCH_MODULE_LABELS,
    );
    expect(visibleNavigationItems("editor").map((item) => item.label)).toEqual([
      "工作台总览",
      "内容库",
      "数据导入",
      "分析中心",
      "账号仪表盘",
      "栏目与活动",
      "运营智能体",
      "生成中心",
      "发布前检查",
      "爆款素材库",
      "账号风格",
      "事实资料",
      "导出与备份",
      "后台任务",
    ]);
    expect(visibleNavigationItems("viewer").map((item) => item.label)).toEqual([
      "工作台总览",
      "内容库",
      "分析中心",
      "账号仪表盘",
      "运营智能体",
      "生成中心",
      "发布前检查",
      "爆款素材库",
      "账号风格",
      "事实资料",
    ]);
  });

  test("derives active categories and role-safe defaults from canonical routes", () => {
    expect(
      activeNavigationCategory(
        "/workspaces/workspace-1/contents/content-1",
        "workspace-1",
      )?.id,
    ).toBe("operations");
    expect(defaultNavigationItem("operations", "viewer")?.href).toBe(
      "/contents",
    );
    expect(defaultNavigationItem("management", "viewer")).toBeUndefined();
    expect(defaultNavigationItem("management", "editor")?.href).toBe(
      "/data-management/exports",
    );
  });

  test("stores only a member-scoped canonical child in its own category", () => {
    const analysis = visibleNavigationItems("admin").find(
      (item) => item.label === "分析中心",
    );
    expect(analysis).toBeDefined();
    writeRecentNavigationPath(
      localStorage,
      "member-admin",
      "operations",
      analysis!,
    );
    expect(
      readRecentNavigationPath(
        localStorage,
        "member-admin",
        "operations",
        "admin",
      ),
    ).toBe("/analysis");
    expect(
      readRecentNavigationPath(
        localStorage,
        "member-viewer",
        "operations",
        "viewer",
      ),
    ).toBeUndefined();
  });

  test.each([
    ["management", "/settings", "viewer"],
    ["operations", "/settings", "admin"],
    ["operations", "https://attacker.example", "admin"],
    ["operations", "/contents?prompt=private", "admin"],
  ] as const)(
    "rejects unsafe or unauthorized recent path %s %s for %s",
    (categoryId, stored, role) => {
      localStorage.setItem(
        `operations-ai:navigation:member-1:${categoryId}`,
        stored,
      );
      expect(
        readRecentNavigationPath(
          localStorage,
          "member-1",
          categoryId,
          role,
        ),
      ).toBeUndefined();
    },
  );

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

  test("shows five primary categories and only the active category children", () => {
    render(
      <WorkspaceShell context={context}>
        <p>页面业务内容</p>
      </WorkspaceShell>,
    );

    const categories = screen.getByRole("navigation", { name: "功能大类" });
    for (const label of ["总览", "运营", "创作", "资产", "管理"]) {
      expect(
        within(categories).getByRole("link", { name: label }),
      ).toBeVisible();
    }
    const children = screen.getByRole("navigation", {
      name: "内容运营功能",
    });
    for (const label of [
      "内容库",
      "数据导入",
      "分析中心",
      "账号仪表盘",
      "栏目与活动",
    ]) {
      expect(within(children).getByRole("link", { name: label })).toBeVisible();
    }
    expect(screen.queryByRole("link", { name: "生成中心" })).toBeNull();
    expect(screen.queryByRole("link", { name: "工作区设置" })).toBeNull();
  });

  test("does not expose an empty management category on a viewer deep link", () => {
    render(
      <SidebarNav
        collapsed={false}
        onNavigate={() => undefined}
        pathname="/workspaces/workspace-1/settings"
        role="viewer"
        workspaceId="workspace-1"
      />,
    );

    expect(screen.queryByRole("link", { name: "管理" })).toBeNull();
    expect(
      screen.queryByRole("navigation", { name: "工作区管理功能" }),
    ).toBeNull();
    expect(
      screen.getByRole("navigation", { name: "工作台总览功能" }),
    ).toBeVisible();
  });

  test("keeps an editor category link on a role-safe child", () => {
    render(
      <SidebarNav
        collapsed={false}
        onNavigate={() => undefined}
        pathname="/workspaces/workspace-1/settings"
        role="editor"
        workspaceId="workspace-1"
      />,
    );

    expect(screen.getByRole("link", { name: "管理" })).toHaveAttribute(
      "href",
      "/workspaces/workspace-1/data-management/exports",
    );
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

  test("restores account scope from a direct account dashboard deep link", () => {
    expect(
      scopeForWorkspacePath(
        "/workspaces/workspace-1/accounts/xhs-account",
        "workspace-1",
        {},
        accounts,
      ),
    ).toEqual({
      platform: "xiaohongshu",
      accountId: "xhs-account",
    });
    expect(
      scopeForWorkspacePath(
        "/workspaces/workspace-1/accounts/unknown-account",
        "workspace-1",
        {},
        accounts,
      ),
    ).toEqual({});
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
  test("provides the current member context to nested workbench pages", () => {
    function ContextProbe() {
      const shellContext = useWorkbenchShellContext();
      return <p>{shellContext?.member_id}:{shellContext?.role}</p>;
    }

    render(
      <WorkspaceShell context={context}>
        <ContextProbe />
      </WorkspaceShell>,
    );
    expect(screen.getByText("member-admin:admin")).toBeVisible();
  });

  test("offers independent easy/professional and guidance controls", async () => {
    const user = userEvent.setup();
    render(<WorkspaceShell context={context}><p>页面业务内容</p></WorkspaceShell>);

    expect(screen.getByRole("radiogroup", { name: "文案模式" })).toBeVisible();
    expect(screen.getByRole("radio", { name: "易懂" })).toBeChecked();
    expect(screen.getByRole("switch", { name: "页面引导" })).toBeChecked();

    await user.click(screen.getByRole("radio", { name: "专业" }));
    expect(screen.getByRole("switch", { name: "页面引导" })).toBeChecked();
    expect(localStorage.getItem(
      "operations-ai:copy-mode:member-admin",
    )).toBe("professional");

    await user.click(screen.getByRole("switch", { name: "页面引导" }));
    expect(screen.getByRole("radio", { name: "专业" })).toBeChecked();
    expect(localStorage.getItem(
      "operations-ai:page-guidance:member-admin",
    )).toBe("off");
  });

  test("supports keyboard selection in the copy mode radio group", async () => {
    const user = userEvent.setup();
    render(<WorkspaceShell context={context}><p>页面业务内容</p></WorkspaceShell>);

    const easy = screen.getByRole("radio", { name: "易懂" });
    const professional = screen.getByRole("radio", { name: "专业" });
    expect(easy).toBeChecked();
    expect(professional).not.toBeChecked();

    easy.focus();
    await user.keyboard("{ArrowRight}");

    expect(easy).not.toBeChecked();
    expect(professional).toBeChecked();
    expect(professional).toHaveFocus();
    expect(localStorage.getItem(
      "operations-ai:copy-mode:member-admin",
    )).toBe("professional");
  });

  test("keeps preferences isolated when the current member changes", () => {
    localStorage.setItem(
      "operations-ai:copy-mode:member-admin",
      "professional",
    );
    const { rerender } = render(
      <WorkspaceShell context={context}><p>管理员页面</p></WorkspaceShell>,
    );
    expect(screen.getByRole("radio", { name: "专业" })).toBeChecked();

    rerender(
      <WorkspaceShell
        context={{
          ...context,
          member_id: "member-viewer",
          member_display_name: "运营查看者",
          role: "viewer",
        }}
      >
        <p>查看者页面</p>
      </WorkspaceShell>,
    );
    expect(screen.getByRole("radio", { name: "易懂" })).toBeChecked();
  });

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
    expect(breadcrumb).toHaveTextContent("运营");
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

  test("preserves validated platform and account scope across navigation", () => {
    navigationState.search = "platform=douyin&account=dy-account";
    render(
      <WorkspaceShell context={context}>
        <p>页面业务内容</p>
      </WorkspaceShell>,
    );

    expect(screen.getByRole("link", { name: "创作" })).toHaveAttribute(
      "href",
      "/workspaces/workspace-1/generation?platform=douyin&account=dy-account",
    );
    expect(screen.getByRole("link", { name: "分析中心" })).toHaveAttribute(
      "href",
      "/workspaces/workspace-1/analysis?platform=douyin&account=dy-account",
    );
    const breadcrumb = screen.getByRole("navigation", { name: "面包屑" });
    expect(
      within(breadcrumb).getByRole("link", { name: "运营" }),
    ).toHaveAttribute(
      "href",
      "/workspaces/workspace-1/contents?platform=douyin&account=dy-account",
    );
  });

  test("leaves an old account route when platform scope becomes incompatible", async () => {
    navigationState.pathname = "/workspaces/workspace-1/accounts/xhs-account";
    const user = userEvent.setup();
    render(
      <WorkspaceShell context={context}>
        <p>账号页面</p>
      </WorkspaceShell>,
    );

    await user.selectOptions(
      screen.getByRole("combobox", { name: "平台范围" }),
      "douyin",
    );
    expect(navigationState.replace).toHaveBeenCalledWith(
      "/workspaces/workspace-1/accounts?platform=douyin",
    );
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
      "264",
    );
    await user.click(screen.getByRole("button", { name: "收起功能列表" }));
    expect(screen.getByRole("complementary")).toHaveAttribute(
      "data-width",
      "80",
    );
    expect(screen.getByRole("navigation", { name: "功能大类" })).toBeVisible();
    expect(
      screen.queryByRole("navigation", { name: "内容运营功能" }),
    ).toBeNull();
    expect(localStorage.getItem("operations-ai:sidebar:member-admin")).toBe(
      "collapsed",
    );
    expect(
      localStorage.getItem(
        "operations-ai:navigation:member-admin:operations",
      ),
    ).toBe("/contents");
    expect(localStorage).toHaveLength(2);
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

  test("uses category-first mobile navigation from the workspace overview", async () => {
    navigationState.pathname = "/workspaces/workspace-1";
    navigationState.search = "platform=douyin&account=dy-account";
    setMobileViewport(true);
    const user = userEvent.setup();
    render(
      <WorkspaceShell context={context}>
        <p>工作台总览</p>
      </WorkspaceShell>,
    );

    await user.click(screen.getByRole("button", { name: "打开主导航" }));
    const dialog = screen.getByRole("dialog", { name: "主导航" });
    expect(
      within(dialog).getByRole("navigation", { name: "功能大类" }),
    ).toBeVisible();
    expect(
      within(dialog).queryByRole("link", { name: "内容库" }),
    ).toBeNull();

    await user.click(within(dialog).getByRole("button", { name: "运营" }));
    expect(
      within(dialog).getByRole("navigation", { name: "内容运营功能" }),
    ).toBeVisible();
    expect(within(dialog).getByRole("link", { name: "内容库" })).toHaveAttribute(
      "href",
      "/workspaces/workspace-1/contents?platform=douyin&account=dy-account",
    );
    const backButton = within(dialog).getByRole("button", {
      name: "返回全部分类",
    });
    expect(backButton).toHaveFocus();
    await user.click(backButton);
    expect(
      within(dialog).getByRole("navigation", { name: "功能大类" }),
    ).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "运营" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "主导航" })).toBeNull();
  });

  test("opens the matching mobile category on a deep link", async () => {
    navigationState.pathname = "/workspaces/workspace-1/facts";
    setMobileViewport(true);
    const user = userEvent.setup();
    render(
      <WorkspaceShell context={context}>
        <p>事实资料页面</p>
      </WorkspaceShell>,
    );

    await user.click(screen.getByRole("button", { name: "打开主导航" }));
    const dialog = screen.getByRole("dialog", { name: "主导航" });
    expect(
      within(dialog).getByRole("navigation", { name: "策略资产功能" }),
    ).toBeVisible();
    expect(
      within(dialog).getByRole("link", { name: "事实资料" }),
    ).toHaveAttribute("aria-current", "page");
    await user.click(
      within(dialog).getByRole("button", { name: "返回全部分类" }),
    );
    expect(within(dialog).getByRole("button", { name: "资产" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "主导航" })).toBeNull();
  });

  test("does not open a mobile category that has no viewer-visible children", async () => {
    navigationState.pathname = "/workspaces/workspace-1/settings";
    setMobileViewport(true);
    const user = userEvent.setup();
    render(
      <WorkspaceShell context={{ ...context, role: "viewer" }}>
        <p>无管理权限页面</p>
      </WorkspaceShell>,
    );

    await user.click(screen.getByRole("button", { name: "打开主导航" }));
    const dialog = screen.getByRole("dialog", { name: "主导航" });
    expect(
      within(dialog).getByRole("navigation", { name: "功能大类" }),
    ).toBeVisible();
    expect(within(dialog).queryByRole("button", { name: "管理" })).toBeNull();
    expect(within(dialog).queryByText("工作区管理")).toBeNull();
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
    localStorage.setItem("operations-ai:sidebar:member-admin", "collapsed");
    localStorage.setItem(
      "operations-ai:navigation:member-admin:operations",
      "/analysis",
    );
    localStorage.setItem("operations-ai:copy-mode:member-admin", "professional");
    localStorage.setItem("operations-ai:page-guidance:member-admin", "off");
    localStorage.setItem("unrelated-preference", "keep");
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
    expect(localStorage.getItem("operations-ai:sidebar:member-admin")).toBeNull();
    expect(
      localStorage.getItem(
        "operations-ai:navigation:member-admin:operations",
      ),
    ).toBeNull();
    expect(
      localStorage.getItem("operations-ai:copy-mode:member-admin"),
    ).toBeNull();
    expect(
      localStorage.getItem("operations-ai:page-guidance:member-admin"),
    ).toBeNull();
    expect(localStorage.getItem("unrelated-preference")).toBe("keep");
  });

  test("clears only navigation display preferences", () => {
    localStorage.setItem("operations-ai:sidebar:member-admin", "collapsed");
    localStorage.setItem(
      "operations-ai:navigation:member-admin:operations",
      "/analysis",
    );
    localStorage.setItem("other", "keep");

    clearNavigationPreferences(localStorage);

    expect(localStorage).toHaveLength(1);
    expect(localStorage.getItem("other")).toBe("keep");
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
