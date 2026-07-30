import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import {
  ContentList,
  normalizeContentFilters,
  updateContentFilters,
} from "./content-list";


afterEach(cleanup);

const accounts = [
  { account_id: "dy-1", platform: "douyin", name: "抖音账号" },
  { account_id: "xhs-1", platform: "xiaohongshu", name: "小红书账号" },
] as const;

const columns = [
  { id: "column-dy", account_id: "dy-1", platform: "douyin", name: "抖音栏目" },
  {
    id: "column-xhs",
    account_id: "xhs-1",
    platform: "xiaohongshu",
    name: "小红书栏目",
  },
] as const;

test("normalizes every URL filter and clears incompatible scope", () => {
  const filters = normalizeContentFilters(
    new URLSearchParams(
      "platform=douyin&account=dy-1&column=column-dy&contentType=video"
        + "&status=published&maturity=24h&query=AI&sort=title_asc&page=3",
    ),
    accounts,
    columns,
  );
  expect(filters).toEqual({
    platform: "douyin",
    account: "dy-1",
    column: "column-dy",
    contentType: "video",
    status: "published",
    maturity: "24h",
    query: "AI",
    metricKey: undefined,
    requiredMetricKeys: [],
    attention: undefined,
    sort: "title_asc",
    page: 3,
  });

  expect(
    normalizeContentFilters(
      new URLSearchParams(
        "platform=xiaohongshu&account=dy-1&column=column-dy&page=4",
      ),
      accounts,
      columns,
    ),
  ).toMatchObject({
    platform: "xiaohongshu",
    account: undefined,
    column: undefined,
    page: 4,
  });
});

test("preserves governed chart drill-down filters in the unified URL state", () => {
  const filters = normalizeContentFilters(
    new URLSearchParams(
      "platform=douyin&account=dy-1&contentType=video&maturity=24h"
      + "&metric_key=views&required_metric_keys=likes"
      + "&required_metric_keys=comments&attention=candidate",
    ),
    accounts,
    columns,
  );
  expect(filters).toMatchObject({
    metricKey: "views",
    requiredMetricKeys: ["likes", "comments"],
    attention: "candidate",
  });
});

test("resets page and clears account and column when parent scope changes", () => {
  const current = normalizeContentFilters(
    new URLSearchParams(
      "platform=douyin&account=dy-1&column=column-dy&page=6",
    ),
    accounts,
    columns,
  );
  expect(updateContentFilters(current, { platform: "xiaohongshu" })).toMatchObject({
    platform: "xiaohongshu",
    account: undefined,
    column: undefined,
    page: 1,
  });
  expect(updateContentFilters(current, { account: undefined })).toMatchObject({
    account: undefined,
    column: undefined,
    page: 1,
  });
});

test("renders desktop rows, 390px cards, viewer safety, and one primary action", () => {
  const onChange = vi.fn();
  render(
    <ContentList
      accounts={[...accounts]}
      columns={[...columns]}
      data={{
        items: [
          {
            id: "content-1",
            title: "AI 工具如何减少重复整理",
            platform: "douyin",
            account_id: "dy-1",
            account_name: "抖音账号",
            column_campaign_id: "column-dy",
            column_campaign_name: "抖音栏目",
            content_type: "video",
            lifecycle_status: "published",
            published_at: "2026-07-29T12:00:00+08:00",
            latest_maturity: "24h",
            data_completeness: 0.75,
            analysis_status: "succeeded",
            risk_status: "high",
            cover: null,
          },
        ],
        total: 1,
        page: 1,
        page_size: 20,
        pages: 1,
      }}
      filters={{
        platform: "douyin",
        account: "dy-1",
        column: "column-dy",
        contentType: "video",
        status: "published",
        maturity: "24h",
        query: "AI",
        sort: "newest",
        page: 1,
      }}
      onFiltersChange={onChange}
      role="viewer"
      workspaceId="workspace-1"
    />,
  );

  for (const label of [
    "平台",
    "账号",
    "栏目/活动",
    "内容类型",
    "生命周期",
    "成熟度",
    "标题搜索",
    "排序",
  ]) {
    expect(screen.getByLabelText(label)).toBeVisible();
  }
  expect(screen.getByRole("table", { name: "内容库桌面列表" })).toBeVisible();
  expect(screen.getByRole("list", { name: "内容库移动卡片" })).toHaveClass(
    "md:hidden",
  );
  expect(screen.getAllByText("高风险")).not.toHaveLength(0);
  expect(screen.queryByRole("link", { name: "新建内容" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "导入数据" })).not.toBeInTheDocument();
  expect(screen.getAllByRole("link", { name: "查看内容" })[0]).toHaveAttribute(
    "href",
    expect.stringContaining("returnTo="),
  );

  fireEvent.change(screen.getByLabelText("生命周期"), {
    target: { value: "draft" },
  });
  expect(onChange).toHaveBeenCalledWith(
    expect.objectContaining({ status: "draft", page: 1 }),
  );
});
