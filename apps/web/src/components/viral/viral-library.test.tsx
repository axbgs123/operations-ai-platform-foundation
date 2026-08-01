import { cleanup, fireEvent, render as rtlRender, screen, waitFor } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { WorkspaceShell } from "@/components/workbench/workspace-shell";
import {
  configureViralThresholds,
  confirmViralCandidate,
  evaluateViralCandidates,
  listViralCandidates,
  listViralLibrary,
  readViralThresholds,
  revokeViralLibraryItem,
} from "@/lib/viral-api";

import { resolveViralAccount, ViralLibrary } from "./viral-library";

vi.mock("next/navigation", () => ({
  usePathname: () => "/workspaces/workspace-1/viral-library",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

const candidate = {
  id: "candidate-1",
  workspace_id: "workspace-1",
  account_id: "account-1",
  content_id: "content-1",
  snapshot_id: "snapshot-1",
  title: "三秒钩子测试内容",
  platform: "douyin" as const,
  content_type: "video" as const,
  maturity_bucket: "24h",
  category: "traffic" as const,
  metric_key: "views",
  actual_value: 1000,
  percentile: 0.95,
  sample_count: 10,
  threshold_value: 950,
  threshold_profile_id: "threshold-1",
  threshold_profile_version: 1,
  objective_profile_id: "objective-1",
  benchmark_profile_id: "benchmark-1",
  sample_snapshot_ids: Array.from({ length: 10 }, (_, index) => `snapshot-${index}`),
  comparison_started_at: "2026-07-01T08:00:00Z",
  comparison_ended_at: "2026-07-10T08:00:00Z",
  reason: "views 进入账号历史前 10%，且达到绝对门槛 950。",
  status: "recommended" as const,
};

const libraryItem = {
  id: "item-1",
  workspace_id: "workspace-1",
  account_id: "account-1",
  candidate_id: candidate.id,
  content_id: candidate.content_id,
  title: candidate.title,
  category: "traffic" as const,
  strategy_tags: ["强钩子"],
  applicable_scenarios: ["新品讲解"],
  structure_summary: "痛点开场—方法拆解—行动引导",
  confirmed_by: "member-1",
  confirmed_at: "2026-07-22T08:00:00Z",
  active: true,
  generation_eligible: true,
  revoked_by: null,
  revoked_at: null,
  revocation_reason: null,
};

const shellContext = {
  workspace_id: "workspace-1",
  workspace_name: "运营工作区",
  member_id: "member-admin",
  member_display_name: "运营管理员",
  role: "admin" as const,
  accounts: [],
  failed_task_count: 0,
};

function renderInWorkspace(
  ui: ReactElement,
  role: "admin" | "editor" | "viewer" = "admin",
) {
  return rtlRender(ui, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <WorkspaceShell context={{ ...shellContext, role }}>
        {children}
      </WorkspaceShell>
    ),
  });
}

vi.mock("@/lib/viral-api", () => ({
  configureViralThresholds: vi.fn(),
  confirmViralCandidate: vi.fn(),
  evaluateViralCandidates: vi.fn(),
  listViralCandidates: vi.fn(),
  listViralLibrary: vi.fn(),
  readViralThresholds: vi.fn(),
  revokeViralLibraryItem: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  });
  sessionStorage.setItem("workspace_csrf", "csrf-token");
  vi.mocked(listViralCandidates).mockResolvedValue([candidate]);
  vi.mocked(listViralLibrary).mockResolvedValue([libraryItem]);
  vi.mocked(confirmViralCandidate).mockResolvedValue(libraryItem);
  const threshold = {
    id: "threshold-1",
    workspace_id: "workspace-1",
    account_id: "account-1",
    version: 1,
    rules: [
      { category: "traffic" as const, metric_key: "views", minimum_value: "900" },
      { category: "engagement" as const, metric_key: "likes", minimum_value: "90" },
      { category: "engagement" as const, metric_key: "comments", minimum_value: "30" },
    ],
    objective_profile_id: "objective-1",
    benchmark_profile_id: "benchmark-1",
  };
  vi.mocked(readViralThresholds).mockResolvedValue(threshold);
  vi.mocked(configureViralThresholds).mockResolvedValue(threshold);
  vi.mocked(evaluateViralCandidates).mockResolvedValue([candidate]);
  vi.mocked(revokeViralLibraryItem).mockResolvedValue({
    ...libraryItem,
    active: false,
    generation_eligible: false,
    revoked_by: "member-1",
    revoked_at: "2026-07-22T09:00:00Z",
    revocation_reason: "策略失效",
  });
});

afterEach(cleanup);

test("explains the easy viral-library purpose and confirmation boundary", async () => {
  renderInWorkspace(
    <ViralLibrary accountId="account-1" workspaceId="workspace-1" />,
  );

  expect(await screen.findByText(
    "保存确认过的优秀内容结构，之后生成内容时可以继续参考。",
  )).toBeVisible();
  expect(screen.getByText(/候选.*确认.*才能.*参考/)).toBeVisible();
});

test("configures an account threshold and runs candidate evaluation", async () => {
  renderInWorkspace(<ViralLibrary accountId="account-1" workspaceId="workspace-1" />);

  await screen.findByRole("heading", { name: "爆款候选" });
  fireEvent.change(screen.getByLabelText("第 1 条指标键"), {
    target: { value: "views" },
  });
  fireEvent.change(screen.getByLabelText("第 1 条绝对最低门槛"), {
    target: { value: "950" },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存门槛并生成候选" }));

  await waitFor(() => {
    expect(configureViralThresholds).toHaveBeenCalledWith(
      "workspace-1",
      "account-1",
      {
        rules: [
          { category: "traffic", metric_key: "views", minimum_value: 950 },
          { category: "engagement", metric_key: "likes", minimum_value: 90 },
          { category: "engagement", metric_key: "comments", minimum_value: 30 },
        ],
      },
      "csrf-token",
    );
    expect(evaluateViralCandidates).toHaveBeenCalledWith(
      "workspace-1",
      "account-1",
      { content_type: "video", maturity_bucket: "24h" },
      "csrf-token",
    );
  });
});

test("shows frozen evidence and confirms a candidate with required metadata", async () => {
  renderInWorkspace(<ViralLibrary accountId="account-1" workspaceId="workspace-1" />);

  expect(await screen.findAllByText("三秒钩子测试内容")).toHaveLength(2);
  expect(screen.getByText("样本 10 · 历史分位 95.0% · 门槛版本 v1")).toBeInTheDocument();
  expect(screen.getByText(candidate.reason)).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("策略标签"), {
    target: { value: "强钩子, 结果前置" },
  });
  fireEvent.change(screen.getByLabelText("适用场景"), {
    target: { value: "新品讲解, 教程" },
  });
  fireEvent.change(screen.getByLabelText("结构总结"), {
    target: { value: "痛点开场—方法拆解—结果证明—行动引导" },
  });
  fireEvent.click(screen.getByRole("button", { name: "确认进入素材库" }));

  await waitFor(() => {
    expect(confirmViralCandidate).toHaveBeenCalledWith(
      "workspace-1",
      "candidate-1",
      {
        strategy_tags: ["强钩子", "结果前置"],
        applicable_scenarios: ["新品讲解", "教程"],
        structure_summary: "痛点开场—方法拆解—结果证明—行动引导",
      },
      "csrf-token",
    );
  });
});

test("lists confirmed material and revokes it without removing history", async () => {
  renderInWorkspace(<ViralLibrary accountId="account-1" workspaceId="workspace-1" />);

  expect(await screen.findByRole("heading", { name: "已确认素材" })).toBeInTheDocument();
  expect(screen.getByText("痛点开场—方法拆解—行动引导")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("撤销原因"), {
    target: { value: "策略失效" },
  });
  fireEvent.click(screen.getByRole("button", { name: "撤销素材" }));

  await waitFor(() => {
    expect(revokeViralLibraryItem).toHaveBeenCalledWith(
      "workspace-1",
      "item-1",
      "策略失效",
      "csrf-token",
    );
  });
});

test("keeps candidates visibly separate from confirmed reusable material", async () => {
  renderInWorkspace(<ViralLibrary accountId="account-1" workspaceId="workspace-1" />);

  expect(await screen.findByText("候选，尚未进入素材库")).toBeVisible();
  expect(screen.getByText("候选不能被生成中心引用")).toBeVisible();
  expect(screen.getByText("历史高分位只表示相关性，不代表确定因果")).toBeVisible();
  expect(screen.getByText("数据成熟度：24h")).toBeVisible();
  expect(screen.getByText("候选产生时间：当前记录未提供")).toBeVisible();

  const confirmedSection = screen.getByRole("region", { name: "已确认素材" });
  expect(confirmedSection).toHaveTextContent("确认人：member-1");
  expect(confirmedSection).toHaveTextContent("确认时间：");
  expect(confirmedSection).toHaveTextContent("生成引用次数：当前记录未提供");
});

test("viewer can read evidence but never sees confirmation or revoke actions", async () => {
  renderInWorkspace(
    <ViralLibrary
      accountId="account-1"
      role="viewer"
      workspaceId="workspace-1"
    />,
    "viewer",
  );

  expect(await screen.findByText("候选，尚未进入素材库")).toBeVisible();
  expect(screen.queryByRole("button", { name: "确认进入素材库" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "撤销素材" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "保存门槛并生成候选" })).not.toBeInTheDocument();
  expect(screen.getByText("建议先做").closest("p")).not.toHaveTextContent(
    /确认候选|确认新版本|添加来源|开始生成/,
  );
  expect(screen.getByText("查看者可查看资产，不能确认、撤销或重新评估")).toBeVisible();
});

test("rejects invalid platform and mismatched account scope", () => {
  const accounts = [
    { account_id: "dy-1", platform: "douyin" as const, name: "抖音账号" },
    {
      account_id: "xhs-1",
      platform: "xiaohongshu" as const,
      name: "小红书账号",
    },
  ];
  expect(resolveViralAccount(accounts, "douyin", "dy-1")?.account_id).toBe("dy-1");
  expect(resolveViralAccount(accounts, "xiaohongshu", "dy-1")).toBeUndefined();
  expect(resolveViralAccount(accounts, "invalid", "dy-1")).toBeUndefined();
  expect(resolveViralAccount(accounts, "douyin", "other-workspace")).toBeUndefined();
});

test("uses a workspace-local return context for content drill-down", async () => {
  renderInWorkspace(<ViralLibrary accountId="account-1" workspaceId="workspace-1" />);
  const candidateLink = await screen.findByRole("link", { name: "查看候选内容" });
  const href = candidateLink.getAttribute("href") ?? "";
  expect(href).toContain("/workspaces/workspace-1/contents/content-1?");
  expect(decodeURIComponent(href)).toContain(
    "returnTo=/workspaces/workspace-1/viral-library?platform=douyin&account=account-1",
  );
  expect(href).not.toContain("http://");
  expect(href).not.toContain("https://");
});

test("uses card sections that stay readable at 390px", async () => {
  renderInWorkspace(<ViralLibrary accountId="account-1" workspaceId="workspace-1" />);
  expect(await screen.findByRole("region", { name: "已确认素材" })).toHaveAttribute(
    "data-mobile-layout",
    "cards",
  );
  expect(screen.getByRole("region", { name: "爆款候选" })).toHaveAttribute(
    "data-mobile-layout",
    "cards",
  );
});
