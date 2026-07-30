import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import type { AnalysisQueuePageData } from "@/lib/analysis-api";

import {
  AnalysisQueue,
  analysisQueueFiltersQuery,
  normalizeAnalysisQueueFilters,
  updateAnalysisQueueFilters,
} from "./analysis-queue";


afterEach(cleanup);

const accounts = [
  { account_id: "dy-1", platform: "douyin", name: "抖音账号" },
  { account_id: "xhs-1", platform: "xiaohongshu", name: "小红书账号" },
] as const;

const data = {
  platform: "douyin",
  account_id: "dy-1",
  status: "failed",
  sort: "newest",
  page: 2,
  page_size: 20,
  total: 21,
  pages: 2,
  items: [
    {
      content_id: "content-1",
      account_id: "dy-1",
      account_name: "抖音账号",
      column_campaign_id: "column-1",
      column_campaign_name: "AI 栏目",
      platform: "douyin",
      content_type: "video",
      status: "failed",
      maturity: "24h",
      sample_count: 4,
      analysis_version: "analysis-v2",
      safe_summary: "分析任务失败，可按安全错误码重试",
      confidence: "low",
      evidence_status: "missing",
      suggestion_status: "none",
    },
  ],
} as AnalysisQueuePageData;

test("normalizes platform-scoped URL filters and rejects incompatible accounts", () => {
  expect(
    normalizeAnalysisQueueFilters(
      new URLSearchParams(
        "platform=douyin&account=dy-1&status=failed&sort=oldest&page=3",
      ),
      accounts,
    ),
  ).toEqual({
    platform: "douyin",
    account: "dy-1",
    status: "failed",
    sort: "oldest",
    page: 3,
  });
  expect(
    normalizeAnalysisQueueFilters(
      new URLSearchParams("platform=xiaohongshu&account=dy-1&page=2"),
      accounts,
    ),
  ).toEqual({
    platform: "xiaohongshu",
    account: undefined,
    status: undefined,
    sort: "newest",
    page: 2,
  });
  expect(
    normalizeAnalysisQueueFilters(
      new URLSearchParams("platform=unknown&account=dy-1&page=9"),
      accounts,
    ),
  ).toEqual({
    platform: undefined,
    account: undefined,
    status: undefined,
    sort: "newest",
    page: 1,
  });
});

test("resets pagination when scope or status changes", () => {
  const current = {
    platform: "douyin" as const,
    account: "dy-1",
    status: "failed" as const,
    sort: "newest" as const,
    page: 4,
  };
  expect(updateAnalysisQueueFilters(current, { status: "completed" })).toEqual({
    ...current,
    status: "completed",
    page: 1,
  });
  expect(
    updateAnalysisQueueFilters(current, { platform: "xiaohongshu" }),
  ).toEqual({
    platform: "xiaohongshu",
    account: undefined,
    status: "failed",
    sort: "newest",
    page: 1,
  });
});

test("renders every governed status and preserves return context in drill-down", () => {
  const onChange = vi.fn();
  render(
    <AnalysisQueue
      accounts={[...accounts]}
      data={data}
      filters={{
        platform: "douyin",
        account: "dy-1",
        status: "failed",
        sort: "newest",
        page: 2,
      }}
      onFiltersChange={onChange}
      role="viewer"
      workspaceId="workspace-1"
    />,
  );

  for (const label of [
    "待分析",
    "分析中",
    "已完成",
    "样本不足",
    "失败",
    "需要配置",
    "建议待采用",
  ]) {
    expect(screen.getByRole("option", { name: label })).toBeInTheDocument();
  }
  const detail = screen.getAllByRole("link", { name: "查看分析" })[0];
  expect(detail).toHaveAttribute(
    "href",
    expect.stringContaining("/contents/content-1?tab=analysis"),
  );
  expect(decodeURIComponent(detail.getAttribute("href") ?? "")).toContain(
    "returnTo=/workspaces/workspace-1/analysis?platform=douyin&account=dy-1&status=failed&sort=newest&page=2",
  );
  expect(screen.getAllByText("无有效 Evidence").length).toBeGreaterThan(0);
  expect(screen.getByRole("list", { name: "分析队列移动卡片" })).toHaveClass(
    "md:hidden",
  );
  expect(screen.queryByRole("button", { name: /触发分析/ })).not.toBeInTheDocument();
  expect(document.body.textContent).not.toContain("完整内部 Prompt");

  fireEvent.change(screen.getByLabelText("分析状态"), {
    target: { value: "completed" },
  });
  expect(onChange).toHaveBeenCalledWith(
    expect.objectContaining({ status: "completed", page: 1 }),
  );
});

test("serializes stable filters for refresh, history, and deep links", () => {
  expect(
    analysisQueueFiltersQuery({
      platform: "douyin",
      account: "dy-1",
      status: "suggestion_pending",
      sort: "oldest",
      page: 3,
    }),
  ).toBe(
    "platform=douyin&account=dy-1&status=suggestion_pending&sort=oldest&page=3",
  );
});
