import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import type { AgentBriefingData, AgentAccount } from "@/lib/agent-api";

import { DailySuggestionCard } from "./daily-suggestion-card";


const accounts: AgentAccount[] = [
  {
    account_id: "11111111-1111-4111-8111-111111111111",
    name: "抖音科技账号",
    platform: "douyin",
  },
];

const briefing: AgentBriefingData = {
  id: "22222222-2222-4222-8222-222222222222",
  workspace_id: "33333333-3333-4333-8333-333333333333",
  input_fingerprint: "a".repeat(64),
  algorithm_version: "operations-agent-briefing-v1",
  tool_catalog_version: "operations-agent-tools-v1",
  data_cutoff_at: "2026-08-05T08:00:00Z",
  primary: {
    candidate_id: "b".repeat(64),
    kind: "pending_analysis",
    platform: "douyin",
    account_id: accounts[0].account_id,
    content_id: "44444444-4444-4444-8444-444444444444",
    is_primary: true,
    safe_title: "先分析最近表现下降的内容",
    safe_reason: "这条内容已有确认数据，但还没有分析结果。",
    blocking_rank: 2,
    severity_rank: 2,
    evidence_rank: 5,
    objective_rank: 5,
    executable_rank: 5,
    repeat_penalty: 0,
    evidence_refs: [
      "content:44444444-4444-4444-8444-444444444444",
      "snapshot:55555555-5555-4555-8555-555555555555",
    ],
  },
  candidates: [],
  created_at: "2026-08-05T08:01:00Z",
};

afterEach(cleanup);

test("shows one operator-friendly daily suggestion without internal enum copy", () => {
  render(
    <DailySuggestionCard
      accounts={accounts}
      briefing={briefing}
      onDefer={vi.fn()}
      onSuppress={vi.fn()}
      role="editor"
      workspaceId={briefing.workspace_id}
    />,
  );

  expect(
    screen.getByRole("heading", { name: "今天建议先处理" }),
  ).toBeVisible();
  expect(
    screen.getByRole("link", { name: "查看处理计划" }),
  ).toBeVisible();
  expect(screen.getByText("抖音 · 抖音科技账号")).toBeVisible();
  expect(screen.getByText("有 2 条可核对依据")).toBeVisible();
  expect(screen.queryByText("pending_analysis")).not.toBeInTheDocument();
  expect(screen.getAllByRole("link", { name: "查看处理计划" })).toHaveLength(1);
});

test("shows the exact preparation route instead of inventing a recommendation", () => {
  render(
    <DailySuggestionCard
      accounts={accounts}
      briefing={{
        ...briefing,
        primary: {
          ...briefing.primary!,
          kind: "incomplete_data",
          safe_title: "先补充发布后的数据",
          safe_reason: "当前数据不足，暂时不能生成可靠建议。",
          evidence_refs: [],
        },
      }}
      onDefer={vi.fn()}
      onSuppress={vi.fn()}
      role="editor"
      workspaceId={briefing.workspace_id}
    />,
  );

  const preparation = screen.getByRole("link", { name: "去导入数据" });
  expect(preparation).toHaveAttribute(
    "href",
    `/workspaces/${briefing.workspace_id}/imports`,
  );
  expect(
    screen.queryByRole("link", { name: "查看处理计划" }),
  ).not.toBeInTheDocument();
});
