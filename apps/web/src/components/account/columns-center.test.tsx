import { cleanup, render, screen } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { WorkspaceShell } from "@/components/workbench/workspace-shell";

import {
  buildColumnFieldViews,
  ColumnsCenter,
  ColumnsCenterPage,
  filterColumnsByScope,
  type ColumnWorkbenchItem,
} from "./columns-center";

const navigationState = vi.hoisted(() => ({
  pathname: "/workspaces/workspace-1/columns",
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

const items: ColumnWorkbenchItem[] = [
  {
    id: "column-1",
    accountId: "account-1",
    accountName: "抖音合成账号",
    platform: "douyin",
    name: "新品周",
    kind: "campaign",
    startsAt: "2026-07-01T00:00:00+08:00",
    endsAt: "2026-07-31T23:59:59+08:00",
    status: "active",
    overrideCount: 2,
    currentVersion: "目标 v3 · 基准 v2",
    fields: [
      {
        label: "运营目标",
        accountDefault: "品牌曝光",
        effectiveValue: "新增关注",
        mode: "temporary_override",
      },
      {
        label: "标题、文案和封面风格",
        accountDefault: "账号风格当前版本",
        effectiveValue: "账号风格当前版本",
        mode: "inherited",
      },
      {
        label: "生成预设",
        accountDefault: "账号默认预设",
        effectiveValue: "账号默认预设",
        mode: "inherited",
      },
    ],
  },
];

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

test("shows the easy columns purpose and read-only next action to viewers", () => {
  vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));
  renderInWorkspace(
    <ColumnsCenterPage workspaceId="workspace-1" />,
    "viewer",
  );

  expect(screen.getByText(
    "管理账号平时使用的栏目规则，以及活动期间临时使用的规则。",
  )).toBeVisible();
  expect(screen.getByText("查看当前生效规则")).toBeVisible();
  expect(
    screen.queryByRole("button", { name: /保存|新建|恢复/ }),
  ).not.toBeInTheDocument();
});

test("visually distinguishes inherited defaults and temporary overrides", () => {
  render(
    <ColumnsCenter
      items={items}
      role="editor"
    />,
  );

  expect(screen.getAllByText("继承账号默认").length).toBeGreaterThan(0);
  expect(screen.getByText("临时覆盖")).toBeVisible();
  expect(screen.getByText("覆盖结束后恢复账号默认")).toBeVisible();
  expect(screen.getByText("目标 v3 · 基准 v2")).toBeVisible();
});

test("viewer receives a read-only column view with no fake save action", () => {
  render(
    <ColumnsCenter
      items={items}
      role="viewer"
    />,
  );

  expect(screen.queryByRole("button", { name: /保存|新建|恢复/ })).not.toBeInTheDocument();
  expect(screen.getByText("只读查看")).toBeVisible();
});

test("keeps the table accessible for narrow screens without dropping scope", () => {
  render(
    <ColumnsCenter
      items={items}
      role="admin"
    />,
  );

  expect(screen.getByRole("region", { name: "栏目与活动列表" })).toHaveClass("overflow-x-auto");
  expect(screen.getByText("抖音合成账号")).toBeVisible();
  expect(screen.getByText("生效中")).toBeVisible();
});

test("removes columns from an incompatible platform or account scope", () => {
  expect(filterColumnsByScope(items, "xiaohongshu", null)).toEqual([]);
  expect(filterColumnsByScope(items, "douyin", "other-account")).toEqual([]);
  expect(filterColumnsByScope(items, "douyin", "account-1")).toEqual(items);
});

test("uses governed style versions and marks the absent preset contract honestly", () => {
  const config = {
    source: "account_default" as const,
    objective_profile: {
      id: "objective-1",
      version: 1,
      objectives: ["reach"],
      metric_weights: { views: 1 },
    },
    benchmark_profile: {
      id: "benchmark-1",
      version: 1,
      sample_size: 30,
    },
  };
  const fields = buildColumnFieldViews(
    {
      objective_profile_id: null,
      benchmark_profile_id: null,
    },
    config,
    config,
    {
      source: "account_default",
      profile_id: "style-account",
      version: 2,
      switches: { title: true, copy: true, cover: true },
      style: {},
    },
    {
      source: "column_override",
      profile_id: "style-column",
      version: 4,
      switches: { title: true, copy: true, cover: true },
      style: {},
    },
  );

  expect(fields).toEqual(expect.arrayContaining([
    expect.objectContaining({
      label: "标题、文案和封面风格",
      accountDefault: "账号风格 v2",
      effectiveValue: "栏目风格 v4",
      mode: "temporary_override",
    }),
    expect.objectContaining({
      label: "生成预设",
      accountDefault: "尚无已配置的账号生成预设",
      effectiveValue: "当前合同未提供栏目级预设覆盖",
      mode: "unavailable",
    }),
  ]));
});
