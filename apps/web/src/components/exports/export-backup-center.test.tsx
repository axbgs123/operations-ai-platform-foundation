import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { WorkspaceShell } from "@/components/workbench/workspace-shell";

import {
  ExportBackupCenter,
  type ExportBackupFixture,
} from "./export-backup-center";

const { confirmZipRestore, previewZipRestore } = vi.hoisted(() => ({
  confirmZipRestore: vi.fn(),
  previewZipRestore: vi.fn(),
}));

vi.mock("@/lib/export-api", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/export-api")>(),
  confirmZipRestore,
  previewZipRestore,
}));

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
  confirmZipRestore.mockReset();
  previewZipRestore.mockReset();
  sessionStorage.setItem("workspace_csrf", "csrf-token");
});

afterEach(cleanup);

test("distinguishes every backup type, restore action and secret exclusion", () => {
  const easy = renderInWorkspace(
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
  expect(screen.getAllByText(/生成指令/).length).toBeGreaterThan(0);
  expect(screen.getAllByText(/资料检索索引/).length).toBeGreaterThan(0);
  expect(screen.getByText(/模型服务私有标识/)).toBeVisible();
  expect(screen.getAllByText(/后台任务运行状态/).length).toBeGreaterThan(0);
  expect(screen.getByText(/下载地址已过期/)).toBeVisible();
  expect(screen.getByText("失败原因编号")).toBeVisible();
  expect(screen.queryByText("安全错误码")).not.toBeInTheDocument();
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

test("professional mode keeps ZIP restore preview and safe error terminology", () => {
  localStorage.setItem("operations-ai:copy-mode:member-admin", "professional");
  const professional = renderInWorkspace(
    <ExportBackupCenter
      evaluatedAt="2026-07-30T00:00:00Z"
      fixture={fixture}
      role="admin"
      workspaceId="ws-1"
    />,
  );

  expect(screen.getByText("ZIP 完整恢复")).toBeVisible();
  expect(screen.getByText("安全错误码")).toBeVisible();
  expect(professional.container).toHaveTextContent("完整 Prompt");
  expect(professional.container).toHaveTextContent("Embedding");
  expect(professional.container).toHaveTextContent("Provider Workspace ID");
  expect(professional.container).toHaveTextContent(
    "Worker claim、lease 和 heartbeat",
  );
  expect(document.body.textContent).not.toContain("synthetic-secret-value");
});

test("ZIP restore requires preview before confirmation and never renders its fingerprint", async () => {
  const preview = {
    id: "restore-1",
    workspace_id: "ws-1",
    target_workspace_id: "ws-1",
    mode: "merge",
    phase: "preview_ready",
    status: "queued",
    preview_id: "preview-1",
    manifest_fingerprint: "manifest-secret-fingerprint",
    preview: {},
    knowledge_indexes: [],
    knowledge_index_message: null,
    error_code: null,
  } as const;
  previewZipRestore.mockResolvedValueOnce(preview);
  confirmZipRestore.mockResolvedValueOnce({
    ...preview,
    phase: "database",
    status: "running",
  });
  renderInWorkspace(
    <ExportBackupCenter fixture={fixture} role="admin" workspaceId="ws-1" />,
  );

  expect(screen.queryByRole("button", {
    name: "再次确认并开始完整恢复",
  })).not.toBeInTheDocument();

  const file = new File(["synthetic zip"], "backup.zip", {
    type: "application/zip",
  });
  fireEvent.change(screen.getByLabelText("选择 ZIP 并生成预览"), {
    target: { files: [file] },
  });

  await waitFor(() => expect(previewZipRestore).toHaveBeenCalledWith(
    "ws-1",
    file,
    "csrf-token",
  ));
  expect(await screen.findByRole("button", {
    name: "再次确认并开始完整恢复",
  })).toBeVisible();
  expect(document.body.textContent).not.toContain("manifest-secret-fingerprint");

  fireEvent.click(screen.getByRole("button", {
    name: "再次确认并开始完整恢复",
  }));
  await waitFor(() => expect(confirmZipRestore).toHaveBeenCalledWith(
    "ws-1",
    preview,
    "csrf-token",
  ));
  expect(document.body.textContent).not.toContain("manifest-secret-fingerprint");
});
