import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { ExperiencePreferencesProvider } from "@/components/workbench/experience-preferences-context";

import {
  AccountDashboard,
  readDashboardModulePreferences,
} from "./account-dashboard";
import { DrillDownContentList } from "./drill-down-content-list";

const shellState = vi.hoisted(() => ({
  role: "admin" as "admin" | "editor" | "viewer",
}));

vi.mock("@/components/workbench/workspace-shell", () => ({
  useWorkbenchShellContext: () => ({
    member_id: "member-admin",
    role: shellState.role,
  }),
}));

function renderDashboard(
  ui: ReactElement,
  role: "admin" | "editor" | "viewer" = "admin",
) {
  shellState.role = role;
  return render(ui, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <ExperiencePreferencesProvider memberId="member-admin">
        {children}
      </ExperiencePreferencesProvider>
    ),
  });
}

const dashboard = {
  account_id: "account-1",
  account_name: "合成小红书账号",
  platform: "xiaohongshu" as const,
  content_type: "image_text" as const,
  maturity_bucket: "24h" as const,
  sample_count: 10,
  data_completeness: 1,
  benchmark_sample_size: 30,
  confidence: "normal" as const,
  explanation: "实际样本 10 条，已按同平台、账号、内容类型和成熟度比较。",
  benchmark_bands: [
    {
      metric_key: "impressions",
      label: "曝光量",
      unit: "count" as const,
      sample_count: 10,
      median: 2450,
      top_25: 2675,
      top_10: 2810,
    },
  ],
  chart_gates: [
    {
      kind: "line" as const,
      eligible: true,
      reason: "同口径有效快照满足趋势展示条件。",
      actual_sample_count: 10,
      required_sample_count: 5,
      missing_metric_keys: [],
    },
    {
      kind: "funnel" as const,
      eligible: true,
      reason: "漏斗必要字段完整。",
      actual_sample_count: 10,
      required_sample_count: 5,
      missing_metric_keys: [],
    },
    {
      kind: "heatmap" as const,
      eligible: true,
      reason: "发布时间样本满足展示条件。",
      actual_sample_count: 10,
      required_sample_count: 10,
      missing_metric_keys: [],
    },
  ],
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
    {
      id: "funnel-impressions-views",
      kind: "funnel" as const,
      title: "曝光到阅读/播放",
      metric_key: null,
      unit: "count" as const,
      sample_count: 10,
      explanation: "同一内容同时具备两阶段指标的样本 10 条。",
      points: [
        { x: "曝光量", y: 20_000, value: null, content_id: null },
        { x: "阅读/播放量", y: 10_000, value: null, content_id: null },
      ],
      drill_down_filter: {
        workspace_id: "workspace-1",
        account_id: "account-1",
        platform: "xiaohongshu" as const,
        content_type: "image_text" as const,
        maturity_bucket: "24h" as const,
        metric_key: null,
        required_metric_keys: ["impressions", "views"],
        attention: null,
      },
    },
    {
      id: "publication-heatmap-impressions",
      kind: "heatmap" as const,
      title: "发布时间与曝光量",
      metric_key: "impressions",
      unit: "count" as const,
      sample_count: 10,
      explanation: "具备发布时间的有效样本 10 条。",
      points: [
        { x: "10:00", y: 1, value: 2000, content_id: "content-1" },
        { x: "20:00", y: 2, value: 2900, content_id: "content-2" },
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
  window.localStorage.clear();
  vi.stubGlobal("fetch", vi.fn().mockImplementation((input: RequestInfo | URL) => {
    const url = String(input);
    return Promise.resolve({
      ok: true,
      json: async () => (
        url.includes("/workbench/overview")
          ? {
              data_status: {
                account_count: 1,
                accounts_missing_recommended_snapshot: 0,
                imports_waiting_confirmation: 0,
              },
              attention: {
                pending_analysis_count: 0,
                high_risk_count: 0,
                low_confidence_ocr_count: 0,
                failed_task_count: 0,
              },
              next_action: null,
              accounts: [{
                account_id: "account-1",
                platform: "xiaohongshu",
                name: "合成小红书账号",
                content_type_counts: { video: 0, image_text: 10 },
                completeness: {
                  score: 0.88,
                  missing_items: [],
                  version: "profile-completeness-v1",
                },
                pending_analysis_count: 0,
                open_risk_count: 0,
                has_current_week_closed_loop: true,
                confirmed_snapshot_count: 10,
                latest_maturity_bucket: "24h",
              }],
            }
          : dashboard
      ),
    });
  }));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("renders evidence-led sections and links charts into the scoped content library", async () => {
  renderDashboard(
    <AccountDashboard accountId="account-1" workspaceId="workspace-1" />,
  );

  expect(await screen.findByRole("heading", { name: "合成小红书账号" })).toBeInTheDocument();
  expect(screen.getByText(
    "只看这个账号的表现变化、目标完成情况和异常内容。",
  )).toBeVisible();
  expect(screen.getByText(
    "数据按当前作品类型和数据采集时间分别计算。",
  )).toBeVisible();
  expect(screen.getByText("实际样本 10 条")).toBeInTheDocument();
  expect(screen.getByText("判断依据充足")).toBeVisible();
  expect(screen.getAllByText("数据采集时间").length).toBeGreaterThan(0);
  expect(screen.getByText(
    "这项数据包含 10 条可用记录；数据完整度 100%；当前判断依据充足。",
  )).toBeVisible();
  expect(document.body.textContent).not.toMatch(/数据成熟度|正常置信度|\bnormal\b|\bAPI\b|门禁/);
  expect(screen.getByRole("heading", { name: "值得关注" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "下一步行动" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "漏斗分析" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "发布时间热力图" })).toBeInTheDocument();

  const chartLink = screen.getByRole("link", { name: /查看曝光量趋势对应内容/ });
  expect(chartLink).toHaveAttribute(
    "href",
    expect.stringContaining("account=account-1"),
  );
  expect(chartLink).toHaveAttribute("href", expect.stringContaining("contentType=image_text"));
  expect(chartLink).toHaveAttribute("href", expect.stringContaining("maturity=24h"));
  expect(chartLink).toHaveAttribute(
    "href",
    expect.stringContaining("metric_key=impressions"),
  );
});

test("keeps the actual sample explanation and omits charts when API marks data insufficient", async () => {
  localStorage.setItem(
    "operations-ai:copy-mode:member-admin",
    "professional",
  );
  vi.mocked(fetch).mockImplementationOnce(async () => ({
    ok: true,
    json: async () => ({
      ...dashboard,
      sample_count: 1,
      confidence: "raw_only",
      explanation: "实际样本 1 条，少于 5 条，仅展示原始指标卡。",
      charts: [],
      benchmark_bands: [],
      chart_gates: dashboard.chart_gates.map((gate) => ({
        ...gate,
        eligible: false,
        actual_sample_count: 1,
        reason: gate.kind === "line"
          ? "趋势图至少需要 2 条同口径有效快照；当前 1 条。"
          : "当前样本不足，暂不展示该图表。",
      })),
      attention_items: [],
    }),
  } as Response));

  renderDashboard(
    <AccountDashboard accountId="account-1" workspaceId="workspace-1" />,
  );

  expect(await screen.findByText("实际样本 1 条")).toBeInTheDocument();
  await waitFor(() => {
    expect(screen.queryByRole("heading", { name: "数据趋势" })).not.toBeInTheDocument();
  });
  expect(screen.getByText(/少于 5 条/)).toBeInTheDocument();
  expect(screen.getByText(/趋势图至少需要 2 条同口径有效快照/)).toBeVisible();
  expect(screen.queryByRole("img", { name: /趋势/ })).not.toBeInTheDocument();
});

test("reloads the dashboard when content type or maturity scope changes", async () => {
  renderDashboard(
    <AccountDashboard accountId="account-1" workspaceId="workspace-1" />,
  );
  await screen.findByRole("heading", { name: "合成小红书账号" });

  fireEvent.change(screen.getByLabelText("内容类型"), {
    target: { value: "video" },
  });
  fireEvent.change(screen.getByLabelText("数据采集时间"), {
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

test("shows benchmark range and API-provided confidence without recomputing gates", async () => {
  renderDashboard(
    <AccountDashboard accountId="account-1" workspaceId="workspace-1" />,
  );

  expect(await screen.findByText("基准范围：最近 30 条同口径内容")).toBeVisible();
  expect(screen.getByText("中位数 2,450")).toBeVisible();
  expect(screen.getByText("前 25% 2,675")).toBeVisible();
  expect(screen.getByText("前 10% 2,810")).toBeVisible();
  expect(screen.getByText("判断依据充足")).toBeVisible();
});

test("professional dashboard preserves maturity, confidence, gate, API, and server explanation wording", async () => {
  localStorage.setItem("operations-ai:copy-mode:member-admin", "professional");
  renderDashboard(
    <AccountDashboard accountId="account-1" workspaceId="workspace-1" />,
  );

  expect(await screen.findByText("正常置信度")).toBeVisible();
  expect(screen.getByText("数据成熟度")).toBeVisible();
  expect(screen.getByLabelText("成熟度")).toBeVisible();
  expect(screen.getByText("仅展示一个同量纲、满足服务端门禁的主要趋势。")).toBeVisible();
  expect(screen.getByText("该指标有效样本 10 条，置信度为 normal。")).toBeVisible();
});

test("isolates optional module preferences by member and account and restores defaults", async () => {
  renderDashboard(
    <AccountDashboard
      accountId="account-1"
      memberId="member-1"
      workspaceId="workspace-1"
    />,
  );
  await screen.findByRole("heading", { name: "合成小红书账号" });

  fireEvent.click(screen.getByRole("button", { name: "隐藏基准区间" }));
  expect(screen.queryByRole("heading", { name: "基准区间" })).not.toBeInTheDocument();
  expect(readDashboardModulePreferences(
    window.localStorage,
    "member-1",
    "account-1",
  )).toEqual(["benchmarks"]);
  expect(readDashboardModulePreferences(
    window.localStorage,
    "member-2",
    "account-1",
  )).toEqual([]);
  expect(readDashboardModulePreferences(
    window.localStorage,
    "member-1",
    "account-2",
  )).toEqual([]);

  fireEvent.click(screen.getByRole("button", { name: "恢复默认布局" }));
  expect(await screen.findByRole("heading", { name: "基准区间" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "下一步行动" })).toBeVisible();
});

test("shows viewers a read-only account-dashboard next action", async () => {
  renderDashboard(
    <AccountDashboard accountId="account-1" workspaceId="workspace-1" />,
    "viewer",
  );

  await screen.findByRole("heading", { name: "合成小红书账号" });
  expect(screen.getByText("查看趋势、目标和异常说明")).toBeVisible();
  expect(
    screen.queryByRole("link", { name: /新建|导入|处理/ }),
  ).not.toBeInTheDocument();
  expect(document.body).not.toHaveTextContent("记录一个可验证变量");
  expect(screen.getByText(
    "查看现有结果；需要继续采集数据或记录实验时，请联系管理员或编辑者。",
  )).toBeVisible();
});

test("retains one title, the mode-aware purpose, and guide in loading, permission, error, and empty branches", async () => {
  vi.mocked(fetch).mockImplementationOnce(() => new Promise(() => undefined));
  const { unmount } = renderDashboard(
    <AccountDashboard accountId="account-1" workspaceId="workspace-1" />,
  );
  expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  expect(screen.getByRole("heading", { level: 1, name: "账号表现" })).toBeVisible();
  expect(screen.getByText("只看这个账号的表现变化、目标完成情况和异常内容。")).toBeVisible();
  expect(screen.getByRole("button", { name: "查看操作说明" })).toBeVisible();

  unmount();
  localStorage.setItem("operations-ai:copy-mode:member-admin", "professional");
  localStorage.setItem("operations-ai:page-guidance:member-admin", "off");
  vi.mocked(fetch).mockResolvedValueOnce({ ok: false, status: 500 } as Response);
  renderDashboard(<AccountDashboard accountId="account-1" workspaceId="workspace-1" />);
  expect(await screen.findByRole("alert")).toHaveTextContent("账号仪表盘加载失败");
  expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  expect(screen.getByText(
    "仅展示单个平台账号、同口径成熟度和满足样本门槛的服务端图表。",
  )).toBeVisible();
  expect(screen.queryByText("建议先做")).not.toBeInTheDocument();

  cleanup();
  localStorage.clear();
  vi.mocked(fetch).mockResolvedValueOnce({
    ok: true,
    json: async () => ({ ...dashboard, goal_cards: [] }),
  } as Response);
  renderDashboard(<AccountDashboard accountId="account-1" workspaceId="workspace-1" />, "viewer");
  expect(await screen.findByText(
    "这里还没有可展示指标；需要补充或确认数据时，请联系管理员或编辑者。",
  )).toBeVisible();
  expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
});
