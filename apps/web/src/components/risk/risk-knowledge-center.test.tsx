import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { RiskKnowledgeCenter } from "./risk-knowledge-center";

vi.mock("@/lib/risk-admin-api", () => ({
  listRiskDocuments: vi.fn(),
  readRiskEvaluation: vi.fn(),
  transitionRiskDocument: vi.fn(),
  listRiskFeedbackCandidates: vi.fn(),
}));

import {
  listRiskFeedbackCandidates,
  listRiskDocuments,
  readRiskEvaluation,
} from "@/lib/risk-admin-api";

const documents = [
  {
    id: "doc-1",
    workspace_id: "workspace-1",
    platform: "douyin",
    scope: "private",
    source_level: "S3",
    title: "人工合成抖音知识",
    source_url: null,
    private_document_id: "synthetic-doc-1",
    published_at: null,
    effective_at: "2026-07-23T12:00:00Z",
    accessed_at: null,
    authorization_status: "authorized",
    reviewed_by: "member-1",
    previous_version_id: null,
    version: 1,
    status: "active",
    created_at: "2026-07-23T11:00:00Z",
    updated_at: "2026-07-23T11:00:00Z",
  },
] as never;

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listRiskDocuments).mockResolvedValue(documents);
  vi.mocked(readRiskEvaluation).mockResolvedValue({
    platform: "douyin",
    fixture_version: "2026-07-23.1",
    sample_count: 11,
    quality_label: "ENGINEERING_REGRESSION_ONLY",
    production_quality_claim_allowed: false,
    metrics: {},
    gate: { passed: true, code: "PASSED", failures: [] },
  } as never);
  vi.mocked(listRiskFeedbackCandidates).mockResolvedValue([]);
});

afterEach(cleanup);

test("admin sees knowledge status, evaluation caveat, and lifecycle actions", async () => {
  render(
    <RiskKnowledgeCenter workspaceId="workspace-1" role="admin" />,
  );

  expect(await screen.findByText("人工合成抖音知识")).toBeInTheDocument();
  expect(
    screen.getByText("草稿 → 已解析 → 待审核 → 生效 → 已替代/已失效"),
  ).toBeVisible();
  expect(screen.getByText("Chunks 与引用检查")).toBeVisible();
  expect(
    screen.getByText("S5 只能作为低置信度提示，不能独立支撑高风险结论"),
  ).toBeVisible();
  expect(screen.getByText("抖音 · 私有 · S3")).toBeInTheDocument();
  expect(screen.getByText("active · v1")).toBeInTheDocument();
  expect(screen.getByText("最近检查")).toBeInTheDocument();
  expect(screen.getByText("尚未检查")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "提交审核" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "生效" })).toBeInTheDocument();
  expect(screen.getByText("工程回归门槛，不是生产准确率")).toBeInTheDocument();
  expect(
    screen.getByText("不能作为生产准确率或平台通过率宣传"),
  ).toBeInTheDocument();
  expect(
    screen.getByText("辅助判断，不保证通过平台审核"),
  ).toBeVisible();

  fireEvent.change(screen.getByRole("combobox", { name: "风控平台" }), {
    target: { value: "xiaohongshu" },
  });
  await waitFor(() => {
    expect(listRiskDocuments).toHaveBeenLastCalledWith(
      "workspace-1",
      "xiaohongshu",
    );
    expect(readRiskEvaluation).toHaveBeenLastCalledWith(
      "workspace-1",
      "xiaohongshu",
    );
    expect(listRiskFeedbackCandidates).toHaveBeenLastCalledWith(
      "workspace-1",
      "xiaohongshu",
    );
  });
});

test("editor and viewer do not receive governance or mutation controls", async () => {
  const { rerender } = render(
    <RiskKnowledgeCenter workspaceId="workspace-1" role="editor" />,
  );
  expect(await screen.findByText("人工合成抖音知识")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "生效" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "提交审核" })).not.toBeInTheDocument();

  rerender(
    <RiskKnowledgeCenter workspaceId="workspace-1" role="viewer" />,
  );
  expect(screen.queryByRole("button", { name: "上传知识" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "提交反馈" })).not.toBeInTheDocument();
});
