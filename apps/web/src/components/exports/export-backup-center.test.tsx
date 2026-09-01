import { cleanup, render, screen } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { WorkspaceShell } from "@/components/workbench/workspace-shell";

import {
  ExportBackupCenter,
  type ExportBackupFixture,
} from "./export-backup-center";

vi.mock("next/navigation", () => ({
  usePathname: () => "/workspaces/ws-1/exports",
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

const shellContext = {
  workspace_id: "ws-1",
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
  return render(ui, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <WorkspaceShell context={{ ...shellContext, role }}>
        {children}
      </WorkspaceShell>
    ),
  });
}

const fixture: ExportBackupFixture = {
  tasks: [
    {
      id: "export-1",
      kind: "csv",
      status: "succeeded",
      created_at: "2026-07-29T08:00:00Z",
      completed_at: "2026-07-29T08:01:00Z",
      download_expires_at: "2026-07-29T08:06:00Z",
      error_code: null,
      requested_by: "member-1",
      file_name: "contents.csv",
    },
    {
      id: "export-2",
      kind: "json",
      status: "queued",
      created_at: "2026-07-29T09:00:00Z",
      completed_at: null,
      download_expires_at: null,
      error_code: null,
      requested_by: "member-2",
      file_name: null,
    },
    {
      id: "export-3",
      kind: "zip",
      status: "running",
      created_at: "2026-07-29T10:00:00Z",
      completed_at: null,
      download_expires_at: null,
      error_code: null,
      requested_by: "member-3",
      file_name: null,
    },
    {
      id: "export-4",
      kind: "markdown",
      status: "failed",
      created_at: "2026-07-29T11:00:00Z",
      completed_at: "2026-07-29T11:01:00Z",
      download_expires_at: null,
      error_code: "export_authorization_revoked",
      requested_by: "member-4",
      file_name: null,
    },
  ],
  restorePreview: [
    {
      action: "create",
      record_type: "platform_account",
      reason: "record_not_present",
    },
    {
      action: "overwrite",
      record_type: "objective_profile",
      reason: "safe_mutable_fields_changed",
    },
    {
      action: "skip",
      record_type: "content",
      reason: "identical_record",
    },
    {
      action: "conflict",
      record_type: "risk_document_metadata",
      reason: "immutable_record_changed",
    },
  ],
};

beforeEach(() => {
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
});

afterEach(cleanup);

test("shows the three operator-facing exports and hides advanced recovery", () => {
  const easy = renderInWorkspace(
    <ExportBackupCenter
      evaluatedAt="2026-07-30T00:00:00Z"
      fixture={fixture}
      role="admin"
      workspaceId="ws-1"
    />,
  );

  expect(screen.getByText(
    "导出运营数据、单条分析报告或工作区结构化数据。",
  )).toBeVisible();
  expect(screen.getByText(
    "按需要导出表格、单条分析报告或可迁移的结构化数据。",
  )).toBeVisible();
  expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);

  for (const label of [
    "CSV 内容与运营数据",
    "Markdown 单条分析报告",
    "JSON 轻量备份",
  ]) {
    expect(screen.getAllByText(label)[0]).toBeVisible();
  }
  expect(screen.queryByRole("button", { name: "创建ZIP 完整备份" })).not.toBeInTheDocument();
  expect(screen.queryByText("JSON 恢复预览")).not.toBeInTheDocument();
  expect(screen.queryByText("完整备份恢复前检查")).not.toBeInTheDocument();
  expect(screen.getByText(/API Key及密文/)).toBeVisible();
  expect(screen.getAllByText(/生成指令/).length).toBeGreaterThan(0);
  expect(screen.getAllByText(/资料检索索引/).length).toBeGreaterThan(0);
  expect(screen.getByText(/模型服务私有标识/)).toBeVisible();
  expect(screen.getAllByText(/后台任务运行状态/).length).toBeGreaterThan(0);
  expect(screen.getByText(/下载地址已过期/)).toBeVisible();
  expect(screen.getAllByText("失败原因编号")).toHaveLength(4);
  expect(screen.queryByText("安全错误码")).not.toBeInTheDocument();
  for (const status of ["已完成", "等待处理", "正在处理", "处理失败"]) {
    expect(screen.getByText(status)).toBeVisible();
  }
  expect(screen.getAllByText("已记录，可在专业模式查看").length).toBeGreaterThan(0);
  expect(easy.container).not.toHaveTextContent("export_authorization_revoked");
  expect(easy.container.textContent).not.toMatch(
    /\b(?:succeeded|queued|running|failed|member-[1-4])\b/,
  );
  expect(screen.getByLabelText("内容 ID")).toBeVisible();
  expect(
    screen.getByRole("button", { name: "创建Markdown 单条分析报告" }),
  ).toBeDisabled();
  expect(screen.queryByLabelText("选择 JSON 并生成预览")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("选择 ZIP 并生成预览")).not.toBeInTheDocument();
  expect(easy.container.textContent).not.toMatch(
    /\b(?:Chunk|Citation|Evidence Bundle|Mock|RAG|OCR|Embedding|Provider|Prompt|Worker|lease|heartbeat|INSUFFICIENT_SAMPLE)\b/,
  );
  expect(easy.container.textContent).not.toMatch(/门禁|向量/);
});

test("easy empty export history uses operator-facing error terminology", () => {
  renderInWorkspace(
    <ExportBackupCenter
      fixture={{ tasks: [], restorePreview: [] }}
      role="admin"
      workspaceId="ws-1"
    />,
  );

  expect(screen.getByText(/状态、完成时间和失败原因编号/)).toBeVisible();
  expect(screen.queryByText(/状态、完成时间和安全错误码/)).not.toBeInTheDocument();
});

test("viewer sees task state but no export or restore write actions", () => {
  renderInWorkspace(
    <ExportBackupCenter
      evaluatedAt="2026-07-30T00:00:00Z"
      fixture={fixture}
      role="viewer"
      workspaceId="ws-1"
    />,
    "viewer",
  );

  expect(screen.getAllByText("CSV 内容与运营数据")[0]).toBeVisible();
  expect(screen.queryByRole("button", { name: /创建/ })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /确认恢复/ })).not.toBeInTheDocument();
});

test("professional mode keeps exact task error terminology", () => {
  localStorage.setItem("operations-ai:copy-mode:member-admin", "professional");
  const professional = renderInWorkspace(
    <ExportBackupCenter
      evaluatedAt="2026-07-30T00:00:00Z"
      fixture={fixture}
      role="admin"
      workspaceId="ws-1"
    />,
  );

  expect(screen.queryByText("ZIP 完整恢复")).not.toBeInTheDocument();
  expect(screen.getAllByText("安全错误码")).toHaveLength(4);
  expect(professional.container).toHaveTextContent("完整 Prompt");
  expect(professional.container).toHaveTextContent("Embedding");
  expect(professional.container).toHaveTextContent("Provider Workspace ID");
  expect(professional.container).toHaveTextContent(
    "Worker claim、lease 和 heartbeat",
  );
  for (const rawValue of [
    "succeeded",
    "queued",
    "running",
    "failed",
    "member-1",
    "export_authorization_revoked",
  ]) {
    expect(professional.container).toHaveTextContent(rawValue);
  }
  expect(document.body.textContent).not.toContain("synthetic-secret-value");
});
