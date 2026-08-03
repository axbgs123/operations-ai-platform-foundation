import { cleanup, fireEvent, render as rtlRender, screen } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { WorkspaceShell } from "@/components/workbench/workspace-shell";
import type { PreflightQueuePageData } from "@/lib/workbench-api";

import {
  PreflightQueue,
  PreflightQueuePage,
  normalizePreflightFilters,
  preflightFiltersQuery,
  type PreflightFilters,
} from "./preflight-queue";

const navigationState = vi.hoisted(() => ({
  search: "",
}));
const loadPreflightQueue = vi.hoisted(() => vi.fn());

vi.mock("next/navigation", () => ({
  usePathname: () => "/workspaces/workspace-1/preflight",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(navigationState.search),
}));

vi.mock("@/lib/workbench-api", () => ({ loadPreflightQueue }));

beforeEach(() => {
  localStorage.clear();
  navigationState.search = "";
  loadPreflightQueue.mockReset();
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

const shellContext = {
  workspace_id: "workspace-1",
  workspace_name: "运营工作区",
  member_id: "member-admin",
  member_display_name: "运营管理员",
  role: "admin" as const,
  accounts: [...accounts],
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

test("explains the easy preflight purpose without weakening missing-evidence safety", () => {
  renderInWorkspace(
    <PreflightQueue
      accounts={[...accounts]}
      data={data}
      filters={filters}
      onFiltersChange={vi.fn()}
      role="editor"
      workspaceId="workspace-1"
    />,
    "editor",
  );

  expect(screen.getByText(
    "集中检查准备发布的内容，处理风险、图片文字识别和资料不足问题。",
  )).toBeVisible();
  expect(screen.getByText(/没有查到规则资料不代表内容安全/)).toBeVisible();
  expect(screen.getByRole("columnheader", { name: "图片文字识别" })).toBeVisible();
  expect(screen.getByRole("columnheader", { name: "判断资料" })).toBeVisible();
  expect(screen.getAllByText("可信度较低，必须人工检查").length).toBeGreaterThan(0);
  expect(screen.getAllByText("已找到可用规则资料").length).toBeGreaterThan(0);
  expect(screen.getAllByText("中风险").length).toBeGreaterThan(0);
  expect(screen.getByText("规则和检查版本已记录")).toBeVisible();
  expect(document.body.textContent).not.toMatch(
    /\b(?:OCR|Evidence|RAG)\b|low_confidence|available|rules-v1|scanner-v1|\bmedium\b/,
  );
});

test("keeps RAG and OCR terminology in professional preflight copy", () => {
  localStorage.setItem("operations-ai:copy-mode:member-admin", "professional");
  renderInWorkspace(
    <PreflightQueue
      accounts={[...accounts]}
      data={data}
      filters={filters}
      onFiltersChange={vi.fn()}
      role="editor"
      workspaceId="workspace-1"
    />,
    "editor",
  );

  expect(screen.getByText(/NO_ACTIVE_RISK_EVIDENCE/)).toBeVisible();
  expect(document.body).toHaveTextContent("RAG");
  expect(document.body).toHaveTextContent("OCR");
  expect(screen.getByRole("columnheader", { name: "Evidence" })).toBeVisible();
  expect(screen.getAllByText("low_confidence").length).toBeGreaterThan(0);
  expect(screen.getAllByText("available").length).toBeGreaterThan(0);
});

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

test("shows governed easy statuses, read-only viewer next steps, mobile cards, and a safe risk drill-down", () => {
  const onFiltersChange = vi.fn();
  renderInWorkspace(
    <PreflightQueue
      accounts={[...accounts]}
      data={data}
      filters={filters}
      onFiltersChange={onFiltersChange}
      role="viewer"
      workspaceId="workspace-1"
    />,
    "viewer",
  );
  for (const label of [
    "待扫描",
    "高风险阻断",
    "图片文字识别可信度低",
    "缺少可用规则资料",
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
  expect(document.body).not.toHaveTextContent("人工核对封面并复检");
  expect(screen.getAllByText(
    "查看风险原因和当前检查状态；需要处理时请联系管理员或编辑者。",
  ).length).toBeGreaterThan(0);
  expect(screen.getByText("建议先做").closest("p")).not.toHaveTextContent(
    /确认候选|确认新版本|添加来源|开始生成/,
  );
  expect(document.body.textContent).not.toContain("PRIVATE_OCR_SOURCE_TEXT");

  fireEvent.change(screen.getByLabelText("检查状态"), {
    target: { value: "high_risk_blocked" },
  });
  expect(onFiltersChange).toHaveBeenCalledWith(
    expect.objectContaining({ status: "high_risk_blocked", page: 1 }),
  );
});

test("keeps the page title, purpose, and reopenable guide in loading and error states", async () => {
  navigationState.search = "platform=douyin&sort=newest&page=1";
  loadPreflightQueue.mockImplementationOnce(() => new Promise(() => undefined));
  const { unmount } = renderInWorkspace(
    <PreflightQueuePage workspaceId="workspace-1" />,
  );

  expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  expect(screen.getByRole("heading", { level: 1, name: "发布前检查" })).toBeVisible();
  expect(screen.getByText(
    "集中检查准备发布的内容，处理风险、图片文字识别和资料不足问题。",
  )).toBeVisible();
  expect(screen.getByRole("button", { name: "查看操作说明" })).toBeVisible();

  unmount();
  localStorage.setItem("operations-ai:copy-mode:member-admin", "professional");
  localStorage.setItem("operations-ai:page-guidance:member-admin", "off");
  loadPreflightQueue.mockRejectedValueOnce(new Error("PRIVATE_PROVIDER_ERROR"));
  renderInWorkspace(<PreflightQueuePage workspaceId="workspace-1" />);

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "发布前检查队列暂时无法读取；已保存内容不会受到影响。",
  );
  expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  expect(screen.getByText(
    "标题、正文和封面 OCR 的确定性规则与 RAG 辅助判断分开展示；无证据不代表安全通过。",
  )).toBeVisible();
  expect(screen.queryByText("建议先做")).not.toBeInTheDocument();
  expect(document.body).not.toHaveTextContent("PRIVATE_PROVIDER_ERROR");
});

test("serializes complete return context deterministically", () => {
  expect(preflightFiltersQuery(filters)).toBe(
    "platform=douyin&account=dy-1&status=low_confidence_ocr&sort=newest&page=2",
  );
});
