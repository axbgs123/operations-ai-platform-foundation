import { cleanup, render, screen } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { WorkspaceShell } from "@/components/workbench/workspace-shell";
import { JobOperations } from "./job-operations";

vi.mock("next/navigation", () => ({
  usePathname: () => "/workspaces/workspace-1/jobs",
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

const shellContext = {
  workspace_id: "workspace-1",
  workspace_name: "运营工作区",
  member_id: "member-admin",
  member_display_name: "运营管理员",
  role: "admin" as const,
  accounts: [],
  failed_task_count: 2,
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

vi.mock("@/lib/operations-api", () => ({
  listOperationalTasks: vi.fn(),
  readOperationsAccess: vi.fn(),
  readOperationsReadiness: vi.fn(),
  mutateOperationalTask: vi.fn(),
}));

import {
  listOperationalTasks,
  readOperationsAccess,
  readOperationsReadiness,
} from "@/lib/operations-api";

const base = {
  task_id: "019fa172-6a11-7000-8000-000000000001",
  task_type: "export",
  workspace_id: "019fa172-6a11-7000-8000-000000000002",
  status: "running",
  progress: 20,
  phase: "writing",
  created_at: "2026-07-27T10:00:00Z",
  started_at: "2026-07-27T10:00:01Z",
  updated_at: "2026-07-27T10:00:02Z",
  completed_at: null,
  retry_count: 0,
  max_retries: 3,
  next_retry_at: null,
  cancelable: true,
  retryable: false,
  error_code: null,
  status_detail: "处理中",
  request_id: "req_01JSAFE000000000000000000",
  fencing_token: 0,
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
  vi.mocked(readOperationsReadiness).mockResolvedValue({
    status: "not_ready",
    components: [
      {
        name: "postgresql",
        status: "ready",
        error_code: null,
      },
      {
        name: "redis",
        status: "not_ready",
        error_code: "DEPENDENCY_UNAVAILABLE",
      },
      {
        name: "s3",
        status: "ready",
        error_code: null,
      },
    ],
  } as never);
  vi.mocked(listOperationalTasks).mockResolvedValue({
    items: [
      base,
      {
        ...base,
        task_id: "019fa172-6a11-7000-8000-000000000003",
        status: "compensation_required",
        phase: "compensation_required",
        cancelable: false,
      },
      {
        ...base,
        task_id: "019fa172-6a11-7000-8000-000000000004",
        status: "dead_letter",
        phase: "upload",
        cancelable: false,
        retryable: true,
        error_code: "STORAGE_TIMEOUT",
      },
      {
        ...base,
        task_id: "019fa172-6a11-7000-8000-000000000005",
        status: "succeeded",
        cancelable: false,
      },
    ],
    total: 4,
    next_offset: null,
  } as never);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

test("admin sees safe states and only valid task actions", async () => {
  renderInWorkspace(<JobOperations workspaceId="workspace-1" role="admin" />);

  expect(screen.getByText(
    "查看导入、分析、生成和备份等耗时任务有没有完成，失败后该怎么处理。",
  )).toBeVisible();
  expect(await screen.findByText("依赖未全部就绪")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "系统依赖状态" })).toBeVisible();
  expect(screen.getByText(/PostgreSQL：已就绪/)).toBeInTheDocument();
  expect(screen.getByText(/Redis：未就绪/)).toBeInTheDocument();
  expect(screen.getByText(/S3：已就绪/)).toBeInTheDocument();
  expect(screen.getByText(
    "自动清理没有完成，需要管理员处理",
  )).toBeInTheDocument();
  expect(screen.getByText(
    "多次尝试仍失败，需要管理员处理",
  )).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "取消任务" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "受控重试" })).toBeInTheDocument();
  expect(screen.getAllByText("已完成")).toHaveLength(1);
});

test("editor is read-only and viewer receives no operations data", async () => {
  const { rerender } = renderInWorkspace(
    <JobOperations workspaceId="workspace-1" role="editor" />,
    "editor",
  );
  expect(await screen.findByText("依赖未全部就绪")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "取消任务" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "受控重试" })).not.toBeInTheDocument();

  rerender(<JobOperations workspaceId="workspace-1" role="viewer" />);
  expect(
    screen.getByText("当前角色没有运维任务查看权限。"),
  ).toBeInTheDocument();
});

test("load failure is rendered without sensitive payload", async () => {
  vi.mocked(listOperationalTasks).mockRejectedValueOnce(
    new Error("DEPENDENCY_NOT_READY"),
  );
  renderInWorkspace(<JobOperations workspaceId="workspace-1" role="admin" />);

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "DEPENDENCY_NOT_READY",
  );
});

test("professional mode preserves readiness, safe codes, and internal failure terms", async () => {
  localStorage.setItem("operations-ai:copy-mode:member-admin", "professional");
  renderInWorkspace(<JobOperations workspaceId="workspace-1" role="admin" />);

  expect(await screen.findByRole("heading", { name: "Readiness" })).toBeVisible();
  expect(screen.getAllByText("安全错误码")[0]).toBeVisible();
  expect(screen.getByText(/需要人工补偿：普通取消不会覆盖/)).toBeVisible();
  expect(screen.getByText(/死信任务：请检查安全错误码/)).toBeVisible();
});

test("no-role access loading branch keeps exactly one page heading", () => {
  vi.mocked(readOperationsAccess).mockReturnValueOnce(new Promise(() => undefined));

  renderInWorkspace(<JobOperations workspaceId="workspace-1" />);

  expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  expect(screen.getByRole("heading", { level: 1, name: "后台任务" })).toBeVisible();
  expect(screen.getByText("正在加载运维权限…")).toBeVisible();
});
