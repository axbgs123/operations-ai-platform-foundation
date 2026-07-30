import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import type { PreflightQueuePageData } from "@/lib/workbench-api";

import {
  PreflightQueue,
  normalizePreflightFilters,
  preflightFiltersQuery,
  type PreflightFilters,
} from "./preflight-queue";


afterEach(cleanup);

const accounts = [
  { account_id: "dy-1", platform: "douyin", name: "抖音账号" },
  { account_id: "xhs-1", platform: "xiaohongshu", name: "小红书账号" },
] as const;

const filters: PreflightFilters = {
  platform: "douyin",
  account: "dy-1",
  status: "low_confidence_ocr",
  sort: "newest",
  page: 2,
};

const data = {
  platform: "douyin",
  account_id: "dy-1",
  status: "low_confidence_ocr",
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
      lifecycle_status: "draft",
      status: "low_confidence_ocr",
      scan_id: "scan-1",
      scan_node: "before_publication",
      highest_severity: "medium",
      ocr_status: "low_confidence",
      evidence_status: "available",
      finding_count: 1,
      rule_version: "rules-v1",
      scan_version: "scanner-v1",
      updated_at: "2026-07-30T00:00:00Z",
      safe_summary: "封面文字需要人工复核",
    },
  ],
} satisfies PreflightQueuePageData;

test("normalizes platform account status sort and pagination safely", () => {
  expect(
    normalizePreflightFilters(
      new URLSearchParams(
        "platform=douyin&account=dy-1&status=high_risk_blocked&sort=oldest&page=3",
      ),
      accounts,
    ),
  ).toEqual({
    platform: "douyin",
    account: "dy-1",
    status: "high_risk_blocked",
    sort: "oldest",
    page: 3,
  });
  expect(
    normalizePreflightFilters(
      new URLSearchParams("platform=xiaohongshu&account=dy-1&status=safe"),
      accounts,
    ),
  ).toEqual({
    platform: "xiaohongshu",
    account: undefined,
    status: undefined,
    sort: "newest",
    page: 1,
  });
});

test("shows governed statuses mobile cards and a safe risk drill-down", () => {
  const onFiltersChange = vi.fn();
  render(
    <PreflightQueue
      accounts={[...accounts]}
      data={data}
      filters={filters}
      onFiltersChange={onFiltersChange}
      role="viewer"
      workspaceId="workspace-1"
    />,
  );
  for (const label of [
    "待扫描",
    "高风险阻断",
    "OCR低置信度",
    "无有效RAG证据",
    "已修改待复检",
    "已通过人工确认",
  ]) {
    expect(screen.getByRole("option", { name: label })).toBeInTheDocument();
  }
  expect(screen.getByRole("list", { name: "发布前检查移动卡片" })).toHaveClass(
    "md:hidden",
  );
  const detail = screen.getAllByRole("link", { name: "查看风险详情" })[0];
  expect(detail).toHaveAttribute(
    "href",
    expect.stringContaining("/contents/content-1?tab=risk"),
  );
  expect(decodeURIComponent(detail.getAttribute("href") ?? "")).toContain(
    "returnTo=/workspaces/workspace-1/preflight?platform=douyin&account=dy-1&status=low_confidence_ocr&sort=newest&page=2",
  );
  expect(screen.queryByRole("button", { name: /扫描|复检/ })).not.toBeInTheDocument();
  expect(document.body.textContent).not.toContain("PRIVATE_OCR_SOURCE_TEXT");

  fireEvent.change(screen.getByLabelText("检查状态"), {
    target: { value: "high_risk_blocked" },
  });
  expect(onFiltersChange).toHaveBeenCalledWith(
    expect.objectContaining({ status: "high_risk_blocked", page: 1 }),
  );
});

test("serializes complete return context deterministically", () => {
  expect(preflightFiltersQuery(filters)).toBe(
    "platform=douyin&account=dy-1&status=low_confidence_ocr&sort=newest&page=2",
  );
});
