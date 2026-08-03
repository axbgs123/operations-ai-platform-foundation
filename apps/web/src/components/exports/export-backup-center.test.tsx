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
  expect(screen.getAllByText("失败原因编号")).toHaveLength(4);
  expect(screen.queryByText("安全错误码")).not.toBeInTheDocument();
  for (const status of ["已完成", "等待处理", "正在处理", "处理失败"]) {
    expect(screen.getByText(status)).toBeVisible();
  }
  expect(screen.getByText("平台账号 · 目标中没有对应记录，将新增")).toBeVisible();
  expect(screen.getByText(
    "目标配置 · 可安全迁移的字段有变化，将覆盖现有记录",
  )).toBeVisible();
  expect(screen.getByText("内容 · 内容一致，无需修改")).toBeVisible();
  expect(screen.getByText(
    "风险规则资料 · 不可变历史记录有变化，已阻断恢复",
  )).toBeVisible();
  expect(screen.getAllByText("已记录，可在专业模式查看").length).toBeGreaterThan(0);
  expect(easy.container).not.toHaveTextContent("export_authorization_revoked");
  expect(easy.container.textContent).not.toMatch(
    /\b(?:succeeded|queued|running|failed|member-[1-4]|platform_account|objective_profile|record_not_present|safe_mutable_fields_changed|identical_record|risk_document_metadata|immutable_record_changed)\b/,
  );
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
    "platform_account · record_not_present",
    "objective_profile · safe_mutable_fields_changed",
    "content · identical_record",
    "risk_document_metadata · immutable_record_changed",
  ]) {
    expect(professional.container).toHaveTextContent(rawValue);
  }
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
  expect(screen.getByText(/阶段：恢复预览已准备，尚未修改正式数据；状态：等待处理/)).toBeVisible();
  expect(screen.getByText("预览标识：已记录，可在专业模式查看")).toBeVisible();
  expect(document.body.textContent).not.toContain("preview_ready");
  expect(document.body.textContent).not.toContain("preview-1");
  expect(document.body.textContent).not.toContain("manifest-secret-fingerprint");

  fireEvent.click(screen.getByRole("button", {
    name: "再次确认并开始完整恢复",
  }));
  await waitFor(() => expect(confirmZipRestore).toHaveBeenCalledWith(
    "ws-1",
    preview,
    "csrf-token",
  ));
  expect(screen.getByText(/阶段：正在恢复结构化记录；状态：正在处理/)).toBeVisible();
  expect(document.body.textContent).not.toContain("database");
  expect(document.body.textContent).not.toContain("running");
  expect(document.body.textContent).not.toContain("manifest-secret-fingerprint");
});

test("professional ZIP restore retains exact phase, task state, and preview identifier", async () => {
  localStorage.setItem("operations-ai:copy-mode:member-admin", "professional");
  const preview = {
    id: "restore-professional",
    workspace_id: "ws-1",
    target_workspace_id: "ws-1",
    mode: "merge",
    phase: "preview_ready",
    status: "queued",
    preview_id: "preview-professional",
    manifest_fingerprint: "professional-manifest-fingerprint",
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

  fireEvent.change(screen.getByLabelText("选择 ZIP 并生成预览"), {
    target: {
      files: [new File(["professional zip"], "professional.zip", {
        type: "application/zip",
      })],
    },
  });

  expect(await screen.findByText(
    /阶段：preview_ready；状态：queued/,
  )).toBeVisible();
  expect(screen.getByText("预览 ID：preview-professional")).toBeVisible();
  fireEvent.click(screen.getByRole("button", {
    name: "再次确认并开始完整恢复",
  }));
  expect(await screen.findByText(
    /阶段：database；状态：running/,
  )).toBeVisible();
  expect(document.body.textContent).not.toContain(
    "professional-manifest-fingerprint",
  );
});
