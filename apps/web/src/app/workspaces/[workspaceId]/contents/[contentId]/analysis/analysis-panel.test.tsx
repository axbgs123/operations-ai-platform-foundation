import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import {
  createAnalysisFeedback,
  markAnalysisViewed,
  requestContentAnalysis,
  saveAnalysisSuggestion,
  updateAnalysisSuggestion,
} from "@/lib/analysis-api";

import { AnalysisPanel } from "./analysis-panel";


const run = {
  id: "run-1",
  content_id: "content-1",
  benchmark_run_id: "benchmark-1",
  snapshot_ids: ["snapshot-1"],
  status: "succeeded" as const,
  trigger_kind: "manual" as const,
  error_code: null,
  model_version: "mock-analysis-v1",
  prompt_version: "analysis-prompt-v1",
  algorithm_version: "analysis-v1",
  benchmark_algorithm_version: "benchmark-v1",
  created_at: "2026-07-22T08:00:00Z",
  completed_at: "2026-07-22T08:00:01Z",
  report: {
    data_performance: {
      summary: "播放量低于账号动态基准中位数。",
      evidence_ids: ["snapshot:snapshot-1:metric:views"],
      trend_conclusion: null,
    },
    title_issues: [{ summary: "标题收益不够前置。", evidence_ids: ["content:title"], confidence: "medium" as const }],
    copy_issues: [{ summary: "正文首段行动不明确。", evidence_ids: ["content:body"], confidence: "medium" as const }],
    cover_issues: [{ summary: "缺少可分析封面。", evidence_ids: ["content:cover_missing"], confidence: "low" as const }],
    evidence: [{ evidence_id: "snapshot:snapshot-1:metric:views", interpretation: "当前播放量证据" }],
    causal_hypotheses: [{ summary: "标题可能相关但不能认定因果。", evidence_ids: ["content:title"], confidence: "low" as const }],
    confidence: "medium" as const,
    recommendations: [{
      id: "recommendation-1",
      summary: "测试收益前置标题。",
      action: "生成一个单变量对照版本。",
      evidence_ids: ["content:title"],
      confidence: "medium" as const,
    }],
    next_experiments: [{
      summary: "进行标题单变量实验。",
      change: "只改标题首句。",
      success_metric: "views",
      evidence_ids: ["content:title"],
      confidence: "medium" as const,
    }],
    degradation_notice: "仅有一个快照，不生成趋势结论。",
  },
};

vi.mock("@/lib/analysis-api", () => ({
  createAnalysisFeedback: vi.fn(),
  markAnalysisViewed: vi.fn(),
  requestContentAnalysis: vi.fn(),
  saveAnalysisSuggestion: vi.fn(),
  updateAnalysisSuggestion: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.setItem("workspace_csrf", "csrf-token");
  vi.mocked(requestContentAnalysis).mockResolvedValue(run);
  vi.mocked(createAnalysisFeedback).mockResolvedValue({ id: "event-1", event_name: "analysis.feedback.useful" });
  vi.mocked(markAnalysisViewed).mockResolvedValue({ id: "view-1", event_name: "analysis.viewed" });
  vi.mocked(saveAnalysisSuggestion).mockResolvedValue({
    id: "suggestion-1",
    analysis_run_id: run.id,
    recommendation_id: "recommendation-1",
    recommendation: run.report.recommendations[0],
    adoption_status: "saved",
    created_at: "2026-07-22T08:00:02Z",
    updated_at: "2026-07-22T08:00:02Z",
  });
  vi.mocked(updateAnalysisSuggestion).mockResolvedValue({
    id: "suggestion-1",
    analysis_run_id: run.id,
    recommendation_id: "recommendation-1",
    recommendation: run.report.recommendations[0],
    adoption_status: "adopted",
    created_at: "2026-07-22T08:00:02Z",
    updated_at: "2026-07-22T08:00:03Z",
  });
});

afterEach(cleanup);

test("renders an evidence-grounded report and completes feedback adoption actions", async () => {
  render(<AnalysisPanel contentId="content-1" workspaceId="workspace-1" />);

  fireEvent.click(screen.getByRole("button", { name: "开始深度分析" }));
  expect(await screen.findByRole("heading", { name: "数据表现" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "证据引用" })).toBeInTheDocument();
  expect(screen.getByText("snapshot:snapshot-1:metric:views")).toBeInTheDocument();
  expect(screen.getByText("播放量低于账号动态基准中位数。")).toBeInTheDocument();
  expect(screen.getByText("仅有一个快照，不生成趋势结论。")).toBeInTheDocument();
  expect(screen.getByText("模型 mock-analysis-v1 · Prompt analysis-prompt-v1 · 算法 analysis-v1 · 基准 benchmark-v1")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "有用" }));
  fireEvent.click(screen.getByRole("button", { name: "保存建议" }));
  await screen.findByRole("button", { name: "标记为已采用" });
  fireEvent.click(screen.getByRole("button", { name: "标记为已采用" }));

  await waitFor(() => {
    expect(createAnalysisFeedback).toHaveBeenCalledWith(
      "content-1",
      "run-1",
      "useful",
      "csrf-token",
      expect.any(String),
    );
    expect(markAnalysisViewed).toHaveBeenCalledWith(
      "content-1",
      "run-1",
      "csrf-token",
    );
    expect(saveAnalysisSuggestion).toHaveBeenCalledWith("content-1", "run-1", "recommendation-1", "csrf-token");
    expect(updateAnalysisSuggestion).toHaveBeenCalledWith("content-1", "suggestion-1", "adopted", "csrf-token");
  });
  expect(await screen.findByText("已采用")).toBeInTheDocument();
});
