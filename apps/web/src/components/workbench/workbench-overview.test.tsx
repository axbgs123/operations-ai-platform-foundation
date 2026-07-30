import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";

import type { WorkbenchOverviewData } from "@/lib/workbench-api";

import { WorkbenchOverview } from "./workbench-overview";


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

afterEach(cleanup);

test("shows operational status in required order without mixed business metrics", () => {
  render(<WorkbenchOverview overview={overview} workspaceId="workspace-1" />);

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
  expect(screen.queryByText(/总播放量|总曝光量|CTR|互动率|综合趋势|综合运营分/)).not.toBeInTheDocument();
});

test("keeps conservative closed-loop status and account scope in dashboard links", () => {
  render(<WorkbenchOverview overview={overview} workspaceId="workspace-1" />);

  expect(screen.getByText("尚未确认闭环")).toBeVisible();
  expect(screen.queryByText("未完成闭环")).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "查看抖音合成账号" })).toHaveAttribute(
    "href",
    "/workspaces/workspace-1/accounts/douyin-account?platform=douyin&account=douyin-account",
  );
});

test("renders unified empty, permission, dependency and loading states", () => {
  const { rerender } = render(
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
  render(
    <WorkbenchOverview
      overview={overview}
      role="viewer"
      workspaceId="workspace-1"
    />,
  );

  expect(screen.queryByRole("link", { name: "新建内容" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "导入数据" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "生成中心" })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "分析中心" })).toBeVisible();
  expect(
    screen.queryByRole("link", { name: "确认等待中的数据导入" }),
  ).not.toBeInTheDocument();
  expect(screen.getByText("该事项需要编辑者或管理员处理")).toBeVisible();
});

test("does not offer account configuration to an empty viewer workspace", () => {
  render(
    <WorkbenchOverview
      role="viewer"
      state="empty"
      workspaceId="workspace-1"
    />,
  );

  expect(screen.queryByRole("link", { name: "配置平台账号" })).not.toBeInTheDocument();
});
