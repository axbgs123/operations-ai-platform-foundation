import { cleanup, render, screen } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import type { WorkbenchOverviewData } from "@/lib/workbench-api";

import { WorkbenchOverview } from "./workbench-overview";
import { WorkspaceShell } from "./workspace-shell";

const navigationState = vi.hoisted(() => ({
  pathname: "/workspaces/workspace-1",
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

const overview = {
  data_status: {
    account_count: 2,
    accounts_missing_recommended_snapshot: 2,
    imports_waiting_confirmation: 1,
  },
  attention: {
    pending_analysis_count: 3,
    high_risk_count: 1,
    low_confidence_ocr_count: 2,
    failed_task_count: 1,
  },
  next_action: {
    kind: "confirm_import",
    label: "确认等待中的数据导入",
    href: "/workspaces/workspace-1/imports",
  },
  accounts: [
    {
      account_id: "douyin-account",
      platform: "douyin",
      name: "抖音合成账号",
      content_type_counts: { video: 3, image_text: 0 },
      completeness: {
        score: 0.7,
        missing_items: ["confirmed_snapshot"],
        version: "profile-completeness-v1",
      },
      pending_analysis_count: 2,
      open_risk_count: 1,
      has_current_week_closed_loop: false,
      confirmed_snapshot_count: 0,
      latest_maturity_bucket: null,
    },
    {
      account_id: "red-account",
      platform: "xiaohongshu",
      name: "小红书合成账号",
      content_type_counts: { video: 0, image_text: 4 },
      completeness: {
        score: 0.9,
        missing_items: [],
        version: "profile-completeness-v1",
      },
      pending_analysis_count: 1,
      open_risk_count: 0,
      has_current_week_closed_loop: true,
      confirmed_snapshot_count: 4,
      latest_maturity_bucket: "72h",
    },
  ],
} as WorkbenchOverviewData;

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

test("shows operational status in required order without mixed business metrics", () => {
  renderInWorkspace(
    <WorkbenchOverview overview={overview} workspaceId="workspace-1" />,
  );

  expect(screen.getByText(
    "看清各账号目前缺什么数据、有哪些待处理内容，以及现在最值得先做哪一件事。",
  )).toBeVisible();
  const headings = screen.getAllByRole("heading", { level: 2 });
  expect(headings.map((heading) => heading.textContent)).toEqual([
    "数据状态",
    "待处理问题",
    "下一步行动",
    "账号状态",
    "快捷操作",
  ]);
  expect(screen.getByText("2 个账号缺少推荐快照")).toBeVisible();
  expect(screen.getByText("抖音合成账号")).toBeVisible();
  expect(screen.getByText("小红书合成账号")).toBeVisible();
  expect(screen.getByText("2 条图片文字识别可信度较低")).toBeVisible();
  expect(screen.getAllByText("数据采集时间").length).toBeGreaterThan(0);
  expect(document.body.textContent).not.toMatch(/\bOCR\b|成熟度/);
  expect(screen.queryByText(/总播放量|总曝光量|CTR|互动率|综合趋势|综合运营分/)).not.toBeInTheDocument();
});

test("keeps conservative closed-loop status and account scope in dashboard links", () => {
  renderInWorkspace(
    <WorkbenchOverview overview={overview} workspaceId="workspace-1" />,
  );

  expect(screen.getByText("尚未确认闭环")).toBeVisible();
  expect(screen.queryByText("未完成闭环")).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "查看抖音合成账号" })).toHaveAttribute(
    "href",
    "/workspaces/workspace-1/accounts/douyin-account?platform=douyin&account=douyin-account",
  );
});

test("renders unified empty, permission, dependency and loading states", () => {
  const { rerender } = renderInWorkspace(
    <WorkbenchOverview state="loading" workspaceId="workspace-1" />,
  );
  expect(screen.getByRole("status", { name: "正在加载工作台" })).toBeVisible();

  rerender(<WorkbenchOverview state="empty" workspaceId="workspace-1" />);
  expect(screen.getByText("还没有平台账号")).toBeVisible();

  rerender(<WorkbenchOverview state="permission" workspaceId="workspace-1" />);
  expect(screen.getByText("当前操作不可用")).toBeVisible();

  rerender(<WorkbenchOverview state="dependency_unavailable" workspaceId="workspace-1" />);
  expect(screen.getByRole("alert")).toHaveTextContent("依赖服务暂不可用");
});

test("does not render fake write shortcuts for a viewer", () => {
  renderInWorkspace(
    <WorkbenchOverview
      overview={overview}
      role="viewer"
      workspaceId="workspace-1"
    />,
    "viewer",
  );

  expect(screen.queryByRole("link", { name: "新建内容" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "导入数据" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "生成中心" })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "分析中心" })).toBeVisible();
  expect(
    screen.queryByRole("link", { name: "确认等待中的数据导入" }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("link", {
    name: "查看等待确认的导入记录；需要确认时请联系管理员或编辑者。",
  })).toBeVisible();
  expect(screen.getByText("查看账号状态和待分析内容")).toBeVisible();
});

test("maps every server-provided overview action to read/contact-only copy for viewers", () => {
  renderInWorkspace(
    <WorkbenchOverview
      overview={{
        ...overview,
        next_action: {
          kind: "review_analysis",
          label: "处理待分析内容",
          href: "/workspaces/workspace-1/analysis",
        },
      }}
      role="viewer"
      workspaceId="workspace-1"
    />,
    "viewer",
  );

  expect(screen.queryByText("处理待分析内容")).not.toBeInTheDocument();
  expect(screen.getByRole("link", {
    name: "查看待分析内容和当前状态；需要处理时请联系管理员或编辑者。",
  })).toBeVisible();
});

test("professional overview preserves OCR and maturity wording", () => {
  localStorage.setItem("operations-ai:copy-mode:member-admin", "professional");
  renderInWorkspace(
    <WorkbenchOverview overview={overview} workspaceId="workspace-1" />,
  );

  expect(screen.getByText("2 条低置信度 OCR")).toBeVisible();
  expect(screen.getAllByText("快照成熟度").length).toBeGreaterThan(0);
});

test("does not offer account configuration to an empty viewer workspace", () => {
  renderInWorkspace(
    <WorkbenchOverview
      role="viewer"
      state="empty"
      workspaceId="workspace-1"
    />,
    "viewer",
  );

  expect(screen.queryByRole("link", { name: "配置平台账号" })).not.toBeInTheDocument();
  expect(screen.getByText(
    "这里还没有平台账号；需要添加时，请联系管理员或编辑者。",
  )).toBeVisible();
  expect(document.body).not.toHaveTextContent("创建抖音或小红书账号后");
});
