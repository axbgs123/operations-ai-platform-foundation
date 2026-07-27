import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { JobOperations } from "./job-operations";

vi.mock("@/lib/operations-api", () => ({
  listOperationalTasks: vi.fn(),
  readOperationsReadiness: vi.fn(),
  mutateOperationalTask: vi.fn(),
}));

import {
  listOperationalTasks,
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
  vi.mocked(readOperationsReadiness).mockResolvedValue({
    status: "not_ready",
    components: [
      {
        name: "redis",
        status: "not_ready",
        error_code: "DEPENDENCY_UNAVAILABLE",
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
  render(<JobOperations workspaceId="workspace-1" role="admin" />);

  expect(await screen.findByText("依赖未全部就绪")).toBeInTheDocument();
  expect(screen.getByText(/需要人工补偿：普通取消不会覆盖/)).toBeInTheDocument();
  expect(screen.getByText(/死信任务：请检查安全错误码/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "取消任务" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "受控重试" })).toBeInTheDocument();
  expect(screen.getAllByText("已完成")).toHaveLength(1);
});

test("editor is read-only and viewer receives no operations data", async () => {
  const { rerender } = render(
    <JobOperations workspaceId="workspace-1" role="editor" />,
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
  render(<JobOperations workspaceId="workspace-1" role="admin" />);

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "DEPENDENCY_NOT_READY",
  );
});
