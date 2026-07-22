import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { AccountDashboard } from "./account-dashboard";
import { DrillDownContentList } from "./drill-down-content-list";


const dashboard = {
  account_id: "account-1",
  account_name: "合成小红书账号",
  platform: "xiaohongshu" as const,
  content_type: "image_text" as const,
  maturity_bucket: "24h" as const,
  sample_count: 10,
  confidence: "normal" as const,
  explanation: "实际样本 10 条，已按同平台、账号、内容类型和成熟度比较。",
  goal_cards: [
    {
      metric_key: "impressions",
      label: "曝光量",
      unit: "count" as const,
      current_value: 2900,
      change_rate: 0.03,
      historical_percentile: 0.95,
      data_completeness: 1,
      sample_count: 10,
      confidence: "normal" as const,
      explanation: "该指标有效样本 10 条，置信度为 normal。",
      drill_down_filter: {
        workspace_id: "workspace-1",
        account_id: "account-1",
        platform: "xiaohongshu" as const,
        content_type: "image_text" as const,
        maturity_bucket: "24h" as const,
        metric_key: "impressions",
        attention: null,
      },
    },
  ],
  charts: [
    {
      id: "trend-impressions",
      kind: "line" as const,
      title: "曝光量趋势",
      metric_key: "impressions",
      unit: "count" as const,
      sample_count: 10,
      explanation: "同口径有效样本 10 条。",
      points: [
        { x: "2026-07-01T00:00:00Z", y: 2000, value: null, content_id: "content-1" },
        { x: "2026-07-02T00:00:00Z", y: 2900, value: null, content_id: "content-2" },
      ],
      drill_down_filter: {
        workspace_id: "workspace-1",
        account_id: "account-1",
        platform: "xiaohongshu" as const,
        content_type: "image_text" as const,
        maturity_bucket: "24h" as const,
        metric_key: "impressions",
        attention: null,
      },
    },
  ],
  attention_items: [
    {
      content_id: "content-2",
      title: "合成候选内容",
      kind: "candidate" as const,
      reason: "曝光量达到样本 P90 以上。",
      drill_down_filter: {
        workspace_id: "workspace-1",
        account_id: "account-1",
        platform: "xiaohongshu" as const,
        content_type: "image_text" as const,
        maturity_bucket: "24h" as const,
        metric_key: "impressions",
        attention: "candidate" as const,
      },
    },
  ],
  next_actions: ["查看候选与异常内容的共同特征。"],
};

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: true,
    json: async () => dashboard,
  }));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("renders evidence-led sections and makes every chart a filtered drill-down link", async () => {
  render(<AccountDashboard accountId="account-1" workspaceId="workspace-1" />);

  expect(await screen.findByRole("heading", { name: "合成小红书账号" })).toBeInTheDocument();
  expect(screen.getByText("实际样本 10 条")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "值得关注" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "下一步行动" })).toBeInTheDocument();

  const chartLink = screen.getByRole("link", { name: /查看曝光量趋势对应内容/ });
  expect(chartLink).toHaveAttribute(
    "href",
    expect.stringContaining("account_id=account-1"),
  );
  expect(chartLink).toHaveAttribute(
    "href",
    expect.stringContaining("metric_key=impressions"),
  );
});

test("keeps the actual sample explanation and omits charts when API marks data insufficient", async () => {
  vi.mocked(fetch).mockResolvedValueOnce({
    ok: true,
    json: async () => ({
      ...dashboard,
      sample_count: 4,
      confidence: "raw_only",
      explanation: "实际样本 4 条，少于 5 条，仅展示原始指标卡。",
      charts: [],
      attention_items: [],
    }),
  } as Response);

  render(<AccountDashboard accountId="account-1" workspaceId="workspace-1" />);

  expect(await screen.findByText("实际样本 4 条")).toBeInTheDocument();
  await waitFor(() => {
    expect(screen.queryByRole("heading", { name: "数据趋势" })).not.toBeInTheDocument();
  });
  expect(screen.getByText(/少于 5 条/)).toBeInTheDocument();
});

test("reloads the dashboard when content type or maturity scope changes", async () => {
  render(<AccountDashboard accountId="account-1" workspaceId="workspace-1" />);
  await screen.findByRole("heading", { name: "合成小红书账号" });

  fireEvent.change(screen.getByLabelText("内容类型"), {
    target: { value: "video" },
  });
  fireEvent.change(screen.getByLabelText("成熟度"), {
    target: { value: "72h" },
  });

  await waitFor(() => {
    const lastUrl = String(vi.mocked(fetch).mock.calls.at(-1)?.[0]);
    expect(lastUrl).toContain("content_type=video");
    expect(lastUrl).toContain("maturity_bucket=72h");
  });
});

test("forwards every paired funnel metric to the drill-down API", async () => {
  vi.mocked(fetch).mockResolvedValueOnce({
    ok: true,
    json: async () => [],
  } as Response);

  render(
    <DrillDownContentList
      filters={{
        workspace_id: "workspace-1",
        account_id: "account-1",
        platform: "xiaohongshu",
        content_type: "image_text",
        maturity_bucket: "24h",
        required_metric_keys: ["impressions", "views"],
      }}
      workspaceId="workspace-1"
    />,
  );

  await waitFor(() => {
    const url = String(vi.mocked(fetch).mock.calls.at(-1)?.[0]);
    expect(url).toContain(
      "required_metric_keys=impressions&required_metric_keys=views",
    );
  });
});
