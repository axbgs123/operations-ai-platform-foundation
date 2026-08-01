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
  ],
  restorePreview: [
    { action: "create", record_type: "content", reason: "目标不存在" },
    { action: "overwrite", record_type: "account", reason: "明确允许覆盖" },
    { action: "skip", record_type: "metric", reason: "内容一致" },
    { action: "conflict", record_type: "fact", reason: "引用不兼容" },
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
});

afterEach(cleanup);

test("distinguishes every backup type, restore action and secret exclusion", () => {
  renderInWorkspace(
    <ExportBackupCenter
      evaluatedAt="2026-07-30T00:00:00Z"
      fixture={fixture}
      role="admin"
      workspaceId="ws-1"
    />,
  );

  expect(screen.getByText(
    "导出运营数据和分析报告，或备份整个工作区后再恢复。",
  )).toBeVisible();
  expect(screen.getByText(
    "系统会先检查版本、文件和冲突；确认恢复前不会改动正式数据。",
  )).toBeVisible();
  expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);

  for (const label of [
    "CSV 内容与运营数据",
    "Markdown 单条分析报告",
    "JSON 轻量备份",
    "ZIP 完整备份",
    "JSON 恢复预览",
    "完整备份恢复前检查",
  ]) {
    expect(screen.getAllByText(label)[0]).toBeVisible();
  }
  for (const label of ["新增", "覆盖", "跳过", "冲突"]) {
    expect(screen.getByText(label)).toBeVisible();
  }
  expect(screen.getByText(/API Key及密文/)).toBeVisible();
  expect(screen.getByText(/Embedding和向量/)).toBeVisible();
  expect(screen.getByText(/下载地址已过期/)).toBeVisible();
  expect(screen.getByLabelText("内容 ID")).toBeVisible();
  expect(
    screen.getByRole("button", { name: "创建Markdown 单条分析报告" }),
  ).toBeDisabled();
  expect(screen.getByLabelText("选择 JSON 并生成预览")).toHaveAttribute(
    "accept",
    "application/json,.json",
  );
  expect(screen.getByLabelText("选择 ZIP 并生成预览")).toHaveAttribute(
    "accept",
    "application/zip,.zip",
  );
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

test("professional mode keeps ZIP restore preview and safe error terminology", () => {
  localStorage.setItem("operations-ai:copy-mode:member-admin", "professional");
  renderInWorkspace(
    <ExportBackupCenter
      evaluatedAt="2026-07-30T00:00:00Z"
      fixture={fixture}
      role="admin"
      workspaceId="ws-1"
    />,
  );

  expect(screen.getByText("ZIP 完整恢复")).toBeVisible();
  expect(screen.getByText("安全错误码")).toBeVisible();
  expect(document.body.textContent).not.toContain("synthetic-secret-value");
});
