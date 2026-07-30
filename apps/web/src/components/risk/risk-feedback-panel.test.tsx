import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { RiskFeedbackPanel } from "./risk-feedback-panel";

vi.mock("@/lib/risk-admin-api", () => ({
  listRiskFeedbackCandidates: vi.fn(),
  reviewRiskFeedback: vi.fn(),
}));

import { listRiskFeedbackCandidates } from "@/lib/risk-admin-api";

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listRiskFeedbackCandidates).mockResolvedValue([
    {
      feedback_id: "feedback-1",
      workspace_id: "workspace-1",
      platform: "douyin",
      finding_reference: "synthetic-finding",
      feedback_type: "false_positive",
      rule_version: "rules-v1",
      evidence_version: "evidence-v1",
      scope: "workspace_private",
      requires_manual_rule_change: true,
      can_modify_public_rules: false,
    },
  ]);
});

afterEach(cleanup);

test("shows pending feedback governance and hides review controls from editor", async () => {
  const { rerender } = render(
    <RiskFeedbackPanel
      platform="xiaohongshu"
      workspaceId="workspace-1"
      role="admin"
    />,
  );

  expect(await screen.findByText("待审核反馈候选")).toBeInTheDocument();
  expect(listRiskFeedbackCandidates).toHaveBeenCalledWith(
    "workspace-1",
    "xiaohongshu",
  );
  expect(screen.getByText("false_positive · synthetic-finding")).toBeInTheDocument();
  expect(screen.getByText("仅工作区私有候选")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "审核候选" })).toBeInTheDocument();

  rerender(
    <RiskFeedbackPanel
      platform="xiaohongshu"
      workspaceId="workspace-1"
      role="editor"
    />,
  );
  expect(screen.queryByRole("button", { name: "审核候选" })).not.toBeInTheDocument();
  expect(screen.getByText("编辑者可提交反馈，不能审核或发布规则")).toBeInTheDocument();
});
