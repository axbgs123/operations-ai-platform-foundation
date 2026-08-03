import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { WorkspaceShell } from "@/components/workbench/workspace-shell";
import type { ContentDetailData } from "@/lib/content-api";

import {
  canonicalContentDetailQuery,
  ContentDetailPage,
  ContentDetailTabs,
  normalizeContentTab,
  safeContentReturnTo,
} from "./content-detail-tabs";

const loadContentDetail = vi.hoisted(() => vi.fn());
const navigationState = vi.hoisted(() => ({
  pathname: "/workspaces/workspace-1/contents/content-1",
  search: "",
  replace: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => navigationState.pathname,
  useRouter: () => ({ replace: navigationState.replace }),
  useSearchParams: () => new URLSearchParams(navigationState.search),
}));

vi.mock("@/lib/content-api", () => ({ loadContentDetail }));

const shellContext = {
  workspace_id: "workspace-1",
  workspace_name: "运营工作区",
  member_id: "member-admin",
  member_display_name: "运营管理员",
  role: "admin" as const,
  accounts: [{
    account_id: "account-1",
    platform: "douyin" as const,
    name: "抖音账号",
  }],
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

beforeEach(() => {
  localStorage.clear();
  loadContentDetail.mockReset();
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

const detail: ContentDetailData = {
  content: {
    id: "content-1",
    workspace_id: "workspace-1",
    account_id: "account-1",
    account_name: "抖音账号",
    platform: "douyin",
    content_type: "video",
    title: "AI 工具如何减少重复整理",
    body: "人工合成正文",
    status: "published",
    column_campaign_id: null,
    column_campaign_name: null,
    work_url: "https://example.com/content",
    platform_content_id: "synthetic-1",
    published_title: "AI 工具如何减少重复整理",
    published_body: "人工合成正文",
    published_at: "2026-07-29T12:00:00+08:00",
    deleted_at: null,
    objective_profile_id: "objective-1",
    benchmark_profile_id: "benchmark-1",
    assets: [],
  },
  lifecycle_stage: "数据采集中",
  snapshots: [
    {
      id: "snapshot-1",
      workspace_id: "workspace-1",
      content_id: "content-1",
      platform: "douyin",
      content_type: "video",
      collected_at: "2026-07-29T13:00:00+08:00",
      age_seconds: 3600,
      maturity_bucket: "1h",
      source: "manual",
      confirmed: true,
      confirmed_at: "2026-07-29T13:01:00+08:00",
      original_screenshot_asset_id: null,
      metrics: [
        {
          key: "views",
          raw_value: null,
          normalized_value: null,
          ocr_confidence: null,
          eligible_for_benchmark: true,
        },
      ],
      completeness: { observed: ["1h"], missing: ["24h", "72h", "7d"], ratio: 0.25 },
    },
  ],
  snapshot_trend: {
    eligible: false,
    reason: "至少需要两条已确认快照。",
    metric_key: null,
    points: [],
  },
  analysis_runs: [],
  risk_scans: [],
  generation_records: [],
};

test("normalizes the five canonical tabs and falls back safely", () => {
  expect(normalizeContentTab("overview")).toBe("overview");
  expect(normalizeContentTab("snapshots")).toBe("snapshots");
  expect(normalizeContentTab("analysis")).toBe("analysis");
  expect(normalizeContentTab("risk")).toBe("risk");
  expect(normalizeContentTab("generation")).toBe("generation");
  expect(normalizeContentTab("secrets")).toBe("overview");
  expect(normalizeContentTab(null)).toBe("overview");
});

test("rejects unsafe return contexts and preserves a complete content-list query", () => {
  const safe = (
    "/workspaces/workspace-1/contents?platform=douyin&account=account-1"
    + "&column=column-1&contentType=video&status=published&maturity=24h"
    + "&query=AI&sort=newest&page=3"
  );
  expect(safeContentReturnTo("workspace-1", safe)).toBe(safe);
  for (const unsafe of [
    "https://evil.example/",
    "//evil.example/",
    "/workspaces/workspace-2/contents",
    "/workspaces/workspace-1/contents/../settings",
    "%252f%252fevil.example",
    "/workspaces/workspace-1/contents?returnTo=%2Foutside",
  ]) {
    expect(safeContentReturnTo("workspace-1", unsafe)).toBe(
      "/workspaces/workspace-1/contents",
    );
  }
});

test("canonicalizes detail scope from the content record rather than forged URL values", () => {
  const query = canonicalContentDetailQuery(
    "workspace-1",
    detail.content,
    new URLSearchParams(
      "tab=risk&platform=xiaohongshu&account=other-account"
      + "&returnTo=%2Fworkspaces%2Fworkspace-2%2Fcontents",
    ),
  );
  const canonical = new URLSearchParams(query);
  expect(canonical.get("tab")).toBe("risk");
  expect(canonical.get("platform")).toBe("douyin");
  expect(canonical.get("account")).toBe("account-1");
  expect(canonical.get("returnTo")).toBe("/workspaces/workspace-1/contents");
});

test("renders five accessible tabs, snapshot gates, lifecycle, and viewer safety", () => {
  const onTabChange = vi.fn();
  renderInWorkspace(
    <ContentDetailTabs
      activeTab="overview"
      detail={detail}
      onTabChange={onTabChange}
      returnTo="/workspaces/workspace-1/contents?page=3"
      role="viewer"
    />,
    "viewer",
  );

  expect(screen.getByText(
    "在一处查看这条作品的数据、分析、风险和生成记录。",
  )).toBeVisible();
  expect(screen.getByText(
    "抖音 · 抖音账号 · 账号默认 · 已发布",
  )).toBeVisible();
  expect(screen.getByText("查看数据、分析和风险标签")).toBeVisible();
  expect(screen.getAllByText("已发布").length).toBeGreaterThan(0);
  expect(screen.getByRole("link", { name: "返回内容库" })).toHaveAttribute(
    "href",
    "/workspaces/workspace-1/contents?page=3",
  );
  expect(screen.queryByRole("link", { name: "生成同类内容" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "保存草稿" })).not.toBeInTheDocument();
  expect(screen.getAllByRole("tab")).toHaveLength(5);

  fireEvent.click(screen.getByRole("tab", { name: "数据快照" }));
  expect(onTabChange).toHaveBeenCalledWith("snapshots");
});

test("keeps populated overview profile references professional-only", () => {
  const easy = renderInWorkspace(
    <ContentDetailTabs
      activeTab="overview"
      detail={detail}
      onTabChange={() => undefined}
      role="editor"
    />,
    "editor",
  );

  expect(screen.getByText(
    "发布时目标配置：已记录，可在专业模式查看",
  )).toBeVisible();
  expect(screen.getByText(
    "发布时基准配置：已记录，可在专业模式查看",
  )).toBeVisible();
  expect(easy.container.textContent).not.toMatch(/objective-1|benchmark-1/);
  expect(easy.container.textContent).not.toMatch(
    /\b(?:Chunk|Citation|Evidence Bundle|Mock|RAG|OCR|Embedding|Provider|Prompt|Worker|lease|heartbeat|INSUFFICIENT_SAMPLE)\b/,
  );

  cleanup();
  localStorage.setItem("operations-ai:copy-mode:member-admin", "professional");
  renderInWorkspace(
    <ContentDetailTabs
      activeTab="overview"
      detail={detail}
      onTabChange={() => undefined}
      role="editor"
    />,
    "editor",
  );
  expect(screen.getByText("objective-1")).toBeVisible();
  expect(screen.getByText("benchmark-1")).toBeVisible();
});

test("shows professional content-detail purpose and safe risk error metadata", () => {
  localStorage.setItem(
    "operations-ai:copy-mode:member-admin",
    "professional",
  );
  renderInWorkspace(
    <ContentDetailTabs
      activeTab="risk"
      detail={{
        ...detail,
        risk_scans: [{
          id: "scan-failed",
          previous_scan_id: null,
          status: "failed",
          node: "before_publication",
          result: null,
          error_code: "RISK_SCAN_FAILED",
          diagnostics: [],
          rule_version: "risk-rules-v1",
          evidence_version: "evidence-v1",
          embedding_model_id: "mock-embedding",
          embedding_version: "v1",
          rag_model_version: "mock-rag-v1",
          scanner_version: "scanner-v1",
          ocr_provider: "mock",
          ocr_model_id: "mock-ocr-v1",
          created_at: "2026-07-29T15:00:00+08:00",
        }],
      }}
      onTabChange={() => undefined}
      role="editor"
    />,
    "editor",
  );

  expect(screen.getByText(/同口径快照/)).toBeVisible();
  expect(screen.getByText(
    "安全错误码：RISK_SCAN_FAILED；失败结果不会保存为成功扫描。",
  )).toBeVisible();
});

test("shows null metrics as missing, one-snapshot explanation, and safe fallbacks", () => {
  renderInWorkspace(
    <ContentDetailTabs
      activeTab="snapshots"
      detail={detail}
      onTabChange={() => undefined}
      role="editor"
    />,
    "editor",
  );
  expect(screen.getAllByText("缺失", { exact: true })).toHaveLength(2);
  expect(screen.getByText("至少需要两条已确认快照。")).toBeVisible();
  expect(screen.getByText("原始值")).toBeVisible();
  expect(screen.getByText("统一口径数值")).toBeVisible();
});

test("requires a shared non-null metric before allowing a snapshot trend", () => {
  const second = {
    ...detail.snapshots[0],
    id: "snapshot-2",
    collected_at: "2026-07-29T14:00:00+08:00",
    metrics: [
      {
        key: "likes",
        raw_value: "12",
        normalized_value: "12",
        ocr_confidence: null,
        eligible_for_benchmark: true,
      },
    ],
  };
  renderInWorkspace(
    <ContentDetailTabs
      activeTab="snapshots"
      detail={{
        ...detail,
        snapshots: [detail.snapshots[0], second],
        snapshot_trend: {
          eligible: false,
          reason: "快照之间缺少共同的有效规范化指标。",
          metric_key: null,
          points: [],
        },
      }}
      onTabChange={() => undefined}
      role="editor"
    />,
    "editor",
  );
  expect(screen.getByText("快照之间缺少共同的有效规范化指标。")).toBeVisible();
  expect(screen.getByText(/未绘制趋势图/)).toBeVisible();
});

test("renders the server-approved same-unit trend with a data-table alternative", () => {
  renderInWorkspace(
    <ContentDetailTabs
      activeTab="snapshots"
      detail={{
        ...detail,
        snapshots: [
          detail.snapshots[0],
          {
            ...detail.snapshots[0],
            id: "snapshot-2",
            collected_at: "2026-07-29T14:00:00+08:00",
          },
        ],
        snapshot_trend: {
          eligible: true,
          reason: "已满足同一内容、同一平台、同一类型和同一指标口径。",
          metric_key: "views",
          points: [
            {
              snapshot_id: "snapshot-1",
              collected_at: "2026-07-29T13:00:00+08:00",
              normalized_value: "100",
            },
            {
              snapshot_id: "snapshot-2",
              collected_at: "2026-07-29T14:00:00+08:00",
              normalized_value: "120",
            },
          ],
        },
      }}
      onTabChange={() => undefined}
      role="viewer"
    />,
    "viewer",
  );
  expect(screen.getByRole("table", { name: "views 单条内容趋势" })).toBeVisible();
  expect(screen.getByText(/共有 2 条有效同口径快照/)).toBeVisible();
});

test("distinguishes analysis, risk, and generation missing-record states", () => {
  const { rerender } = renderInWorkspace(
    <ContentDetailTabs
      activeTab="analysis"
      detail={detail}
      onTabChange={() => undefined}
      role="editor"
    />,
    "editor",
  );
  expect(screen.getByText("当前记录未提供分析结果")).toBeVisible();
  expect(screen.getByRole("button", { name: "开始深度分析" })).toBeVisible();

  rerender(
    <ContentDetailTabs
      activeTab="risk"
      detail={detail}
      onTabChange={() => undefined}
      role="editor"
    />,
  );
  expect(screen.getByText("尚未扫描")).toBeVisible();
  expect(screen.getByText("辅助判断，不保证通过平台审核")).toBeVisible();
  expect(screen.queryByText("安全通过")).not.toBeInTheDocument();

  rerender(
    <ContentDetailTabs
      activeTab="generation"
      detail={detail}
      onTabChange={() => undefined}
      role="editor"
    />,
  );
  expect(screen.getByText("当前记录未提供生成关系")).toBeVisible();
});

test("supports arrow, Home, and End keyboard navigation", () => {
  const onTabChange = vi.fn();
  renderInWorkspace(
    <ContentDetailTabs
      activeTab="overview"
      detail={detail}
      onTabChange={onTabChange}
      role="admin"
    />,
    "admin",
  );
  const overview = screen.getByRole("tab", { name: "概览" });
  expect(screen.getByRole("button", { name: "保存草稿" })).toBeInTheDocument();
  fireEvent.keyDown(overview, { key: "End" });
  expect(onTabChange).toHaveBeenCalledWith("generation");
  fireEvent.keyDown(overview, { key: "ArrowRight" });
  expect(onTabChange).toHaveBeenCalledWith("snapshots");
});

test("renders governed analysis, cited risk, and safe generation metadata in easy mode without primary technical leaks or secrets", () => {
  const governed = {
    ...detail,
    analysis_runs: [
      {
        id: "analysis-1",
        content_id: "content-1",
        benchmark_run_id: "benchmark-1",
        snapshot_ids: ["snapshot-1"],
        status: "succeeded",
        trigger_kind: "manual",
        report: {
          data_performance: {
            summary: "当前表现有可验证数据支持",
            evidence_ids: ["metric:views"],
            trend_conclusion: null,
          },
          title_issues: [],
          copy_issues: [],
          cover_issues: [],
          evidence: [
            {
              evidence_id: "metric:views",
              interpretation: "播放量原始值",
            },
          ],
          causal_hypotheses: [
            {
              summary: "仅为待验证原因假设",
              evidence_ids: ["metric:views"],
              confidence: "low",
            },
          ],
          confidence: "low",
          recommendations: [
            {
              id: "recommendation-1",
              summary: "测试标题前置信息",
              action: "下一条内容只调整标题",
              evidence_ids: ["metric:views"],
              confidence: "low",
            },
          ],
          next_experiments: [
            {
              summary: "单变量实验",
              change: "只改标题",
              success_metric: "views",
              evidence_ids: ["metric:views"],
              confidence: "low",
            },
          ],
          degradation_notice: "样本不足，已降低置信度",
        },
        error_code: null,
        model_config_id: null,
        model_provider: "mock",
        model_version: "mock-analysis-v1",
        provider_contract_version: "mock-structured-v1",
        model_config_version: "mock-static-v1",
        prompt_version: "analysis-prompt-v1",
        algorithm_version: "analysis-v1",
        benchmark_algorithm_version: "benchmark-v1",
        created_at: "2026-07-29T13:00:00+08:00",
        completed_at: "2026-07-29T13:01:00+08:00",
      },
    ],
    risk_scans: [
      {
        id: "scan-1",
        previous_scan_id: null,
        status: "succeeded",
        node: "before_publication",
        result: {
          findings: [
            {
              risk_type: "contact_format",
              severity: "high",
              matched_content: "合成命中文字",
              region: "cover",
              ocr_bbox: [0.1, 0.1, 0.2, 0.2],
              ocr_confidence: 0.62,
              evidence_document_ids: ["document-1"],
              citations: [
                {
                  document_title: "合成规则说明",
                  source_level: "S1",
                  source_url: "https://example.test/rule",
                  private_document_id: null,
                  document_version: 2,
                  effective_at: "2026-07-01T00:00:00+08:00",
                  chunk_id: "chunk-1",
                  chunk_location: "section-1",
                  excerpt: "合成短摘录",
                },
              ],
              reason: "确定性格式命中",
              suggestion: "移除联系方式格式",
              origin: "deterministic_and_rag",
              requires_human_review: true,
              deterministic_confirmed: true,
            },
          ],
          ocr_status: "succeeded",
          diagnostics: [],
          error_code: null,
          versions: {
            rule_version: "risk-rules-v1",
            evidence_version: "evidence-v1",
            embedding_model_id: "mock-embedding",
            embedding_version: "v1",
            embedding_dimension: 4,
            rag_model_version: "mock-rag-v1",
            scanner_version: "scanner-v1",
            ocr_provider: "mock",
            ocr_model_id: "mock-ocr-v1",
            ocr_contract_version: "mock-ocr-v1",
            ocr_config_version: "mock-static-v1",
          },
          scanned_at: "2026-07-29T14:00:00+08:00",
          disclaimer: "辅助判断，不保证通过平台审核",
        },
        error_code: null,
        diagnostics: [],
        rule_version: "risk-rules-v1",
        evidence_version: "evidence-v1",
        embedding_model_id: "mock-embedding",
        embedding_version: "v1",
        rag_model_version: "mock-rag-v1",
        scanner_version: "scanner-v1",
        ocr_provider: "mock",
        ocr_model_id: "mock-ocr-v1",
        created_at: "2026-07-29T14:00:00+08:00",
      },
    ],
    generation_records: [
      {
        id: "generation-1",
        kind: "cover",
        status: "succeeded",
        provider: "mock",
        model_id: "mock-image-v1",
        contract_version: "cover-contract-v1",
        account_style_version: null,
        column_override_version: null,
        confirmed_facts_version: null,
        viral_reference_count: null,
        preset_version: null,
        original_result: null,
        final_result: null,
        adoption_status: null,
        modification_magnitude: null,
        created_at: "2026-07-29T15:00:00+08:00",
        completed_at: "2026-07-29T15:01:00+08:00",
      },
    ],
    api_key: "must-not-render",
    prompt_text: "must-not-render",
    provider_workspace_id: "must-not-render",
  } as unknown as ContentDetailData;

  const { rerender } = renderInWorkspace(
    <ContentDetailTabs
      activeTab="analysis"
      detail={governed}
      onTabChange={() => undefined}
      role="editor"
    />,
    "editor",
  );
  expect(screen.getByText("当前表现有可验证数据支持")).toBeVisible();
  expect(screen.getByText(/本次判断参考：metric:views/)).toBeVisible();
  expect(screen.getAllByText(/判断可靠程度/).length).toBeGreaterThan(0);
  expect(document.body.textContent).not.toMatch(
    /\b(?:Evidence|Provider|RAG|Embedding)\b|analysis-prompt-v1|analysis-v1|benchmark-v1/,
  );

  rerender(
    <ContentDetailTabs
      activeTab="risk"
      detail={governed}
      onTabChange={() => undefined}
      role="editor"
    />,
  );
  expect(screen.getByText("固定规则和已保存资料共同判断")).toBeVisible();
  expect(screen.getByText(/可信度较低，必须人工检查/)).toBeVisible();
  expect(screen.getByText("高风险")).toBeVisible();
  expect(screen.getByText("联系方式格式风险")).toBeVisible();
  expect(screen.getByText("原因：确定性格式命中")).toBeVisible();
  expect(screen.getByText(/位置：封面；命中：合成命中文字/)).toBeVisible();
  expect(screen.getByText(/合成规则说明 2/)).toBeVisible();
  expect(document.body.textContent).not.toMatch(
    /\b(?:RAG|OCR|Embedding)\b|succeeded|before_publication|contact_format|risk-rules-v1|evidence-v1/,
  );

  rerender(
    <ContentDetailTabs
      activeTab="risk"
      detail={{
        ...governed,
        risk_scans: [
          {
            ...governed.risk_scans[0],
            id: "scan-2",
            previous_scan_id: "scan-1",
            status: "failed",
            result: null,
            error_code: "RISK_SCAN_FAILED",
            created_at: "2026-07-29T15:00:00+08:00",
          },
          governed.risk_scans[0],
        ],
      }}
      onTabChange={() => undefined}
      role="editor"
    />,
  );
  expect(screen.getByText("扫描任务失败")).toBeVisible();
  expect(screen.getByText(
    "本次风险检查没有完成，不能当作安全通过。请重新检查或联系管理员。",
  )).toBeVisible();
  expect(screen.queryByText(/安全错误码：RISK_SCAN_FAILED/)).not.toBeInTheDocument();
  expect(screen.getByText("最近一次成功扫描（历史参考）")).toBeVisible();
  expect(screen.getByText("固定规则和已保存资料共同判断")).toBeVisible();
  expect(screen.queryByText("当前扫描没有发现")).not.toBeInTheDocument();

  rerender(
    <ContentDetailTabs
      activeTab="generation"
      detail={governed}
      onTabChange={() => undefined}
      role="editor"
    />,
  );
  expect(screen.getAllByText("已记录，可在专业模式查看").length).toBeGreaterThan(0);
  expect(screen.getAllByText("当前记录未提供").length).toBeGreaterThan(0);
  expect(screen.getByText(/模拟体验，不调用真实模型，也不会产生模型费用/)).toBeVisible();
  expect(document.body.textContent).not.toMatch(/\bProvider\b|\bmock\b|succeeded|cover-contract-v1/);
  expect(document.body).not.toHaveTextContent("must-not-render");
});

test("preserves the exact professional analysis, risk, and generation terminology", () => {
  localStorage.setItem("operations-ai:copy-mode:member-admin", "professional");
  const governed = {
    ...detail,
    analysis_runs: [{
      id: "analysis-professional",
      content_id: "content-1",
      benchmark_run_id: "benchmark-1",
      snapshot_ids: ["snapshot-1"],
      status: "succeeded",
      trigger_kind: "manual",
      report: {
        data_performance: { summary: "专业分析", evidence_ids: ["metric:views"], trend_conclusion: null },
        title_issues: [], copy_issues: [], cover_issues: [],
        evidence: [{ evidence_id: "metric:views", interpretation: "播放量" }],
        causal_hypotheses: [{ summary: "专业假设", evidence_ids: ["metric:views"], confidence: "low" }],
        confidence: "low",
        recommendations: [], next_experiments: [], degradation_notice: null,
      },
      error_code: null, model_config_id: null, model_provider: "mock",
      model_version: "mock-analysis-v1", provider_contract_version: "mock-structured-v1",
      model_config_version: "mock-static-v1", prompt_version: "analysis-prompt-v1",
      algorithm_version: "analysis-v1", benchmark_algorithm_version: "benchmark-v1",
      created_at: "2026-07-29T13:00:00+08:00", completed_at: "2026-07-29T13:01:00+08:00",
    }],
    risk_scans: [{
      id: "scan-professional", previous_scan_id: null, status: "succeeded",
      node: "before_publication", error_code: null, diagnostics: [],
      rule_version: "risk-rules-v1", evidence_version: "evidence-v1",
      embedding_model_id: "mock-embedding", embedding_version: "v1",
      rag_model_version: "mock-rag-v1", scanner_version: "scanner-v1",
      ocr_provider: "mock", ocr_model_id: "mock-ocr-v1",
      created_at: "2026-07-29T14:00:00+08:00",
      result: {
        findings: [{
          risk_type: "contact_format", severity: "high", matched_content: "合成命中",
          region: "cover", ocr_bbox: null, ocr_confidence: 0.62,
          evidence_document_ids: [], citations: [], reason: "确定性格式命中",
          suggestion: "移除格式", origin: "deterministic_and_rag",
          requires_human_review: true, deterministic_confirmed: true,
        }],
        ocr_status: "succeeded", diagnostics: [], error_code: null,
        versions: {
          rule_version: "risk-rules-v1", evidence_version: "evidence-v1",
          embedding_model_id: "mock-embedding", embedding_version: "v1",
          embedding_dimension: 4, rag_model_version: "mock-rag-v1",
          scanner_version: "scanner-v1", ocr_provider: "mock",
          ocr_model_id: "mock-ocr-v1", ocr_contract_version: "mock-ocr-v1",
          ocr_config_version: "mock-static-v1",
        },
        scanned_at: "2026-07-29T14:00:00+08:00",
        disclaimer: "辅助判断，不保证通过平台审核",
      },
    }],
    generation_records: [{
      id: "generation-professional", kind: "cover", status: "succeeded",
      provider: "mock", model_id: "mock-image-v1", contract_version: "cover-contract-v1",
      account_style_version: null, column_override_version: null,
      confirmed_facts_version: null, viral_reference_count: null, preset_version: null,
      original_result: null, final_result: null, adoption_status: null,
      modification_magnitude: null, created_at: "2026-07-29T15:00:00+08:00",
      completed_at: "2026-07-29T15:01:00+08:00",
    }],
  } as ContentDetailData;

  const { rerender } = renderInWorkspace(
    <ContentDetailTabs activeTab="analysis" detail={governed} onTabChange={() => undefined} role="editor" />,
    "editor",
  );
  expect(screen.getByText(/Evidence：metric:views/)).toBeVisible();
  expect(screen.getAllByText(/置信度/).length).toBeGreaterThan(0);
  expect(screen.getByText("analysis-prompt-v1")).toBeVisible();

  rerender(<ContentDetailTabs activeTab="risk" detail={governed} onTabChange={() => undefined} role="editor" />);
  expect(screen.getByText("确定性规则 + RAG")).toBeVisible();
  expect(screen.getByText(/OCR 置信度：62%/)).toBeVisible();
  expect(screen.getByText(/Embedding/)).toBeVisible();
  expect(screen.getByText("risk-rules-v1")).toBeVisible();

  rerender(<ContentDetailTabs activeTab="generation" detail={governed} onTabChange={() => undefined} role="editor" />);
  expect(screen.getByText("Provider 与模型安全状态")).toBeVisible();
  expect(screen.getByText("封面生成任务 · succeeded")).toBeVisible();
  expect(screen.getByText("cover-contract-v1")).toBeVisible();
});

test("keeps Viewer empty guidance read/contact-only", () => {
  renderInWorkspace(
    <ContentDetailTabs activeTab="snapshots" detail={{ ...detail, snapshots: [] }} onTabChange={() => undefined} role="viewer" />,
    "viewer",
  );

  expect(screen.getByText(
    "这里还没有数据快照；需要补充或确认时，请联系管理员或编辑者。",
  )).toBeVisible();
  expect(document.body).not.toHaveTextContent("添加并人工确认数据快照");
});

test("keeps title, purpose, and guide in content-detail loading and safe error states", async () => {
  loadContentDetail.mockImplementationOnce(() => new Promise(() => undefined));
  const { unmount } = renderInWorkspace(
    <ContentDetailPage contentId="content-1" workspaceId="workspace-1" />,
  );
  expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  expect(screen.getByRole("heading", { level: 1, name: "内容详情" })).toBeVisible();
  expect(screen.getByText("在一处查看这条作品的数据、分析、风险和生成记录。")).toBeVisible();
  expect(screen.getByRole("button", { name: "查看操作说明" })).toBeVisible();

  unmount();
  localStorage.setItem("operations-ai:copy-mode:member-admin", "professional");
  localStorage.setItem("operations-ai:page-guidance:member-admin", "off");
  loadContentDetail.mockRejectedValueOnce(new Error("PRIVATE_PROVIDER_ERROR"));
  renderInWorkspace(<ContentDetailPage contentId="content-1" workspaceId="workspace-1" />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "内容详情暂时无法读取；已保存内容不会受到影响。",
  );
  expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  expect(screen.getByText(
    "展示服务端可确认的生命周期、同口径快照、分析版本、风险扫描和安全关联生成记录。",
  )).toBeVisible();
  expect(screen.queryByText("建议先做")).not.toBeInTheDocument();
  expect(document.body).not.toHaveTextContent("PRIVATE_PROVIDER_ERROR");
});
