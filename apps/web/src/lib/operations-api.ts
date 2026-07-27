import type { components } from "@operations-ai/shared-schemas";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type OperationalTask = components["schemas"]["OperationalTask"];
export type TaskListResponse = components["schemas"]["TaskListResponse"];
export type ReadinessResponse = components["schemas"]["ReadinessResponse"];
export type OperationsAccessResponse =
  components["schemas"]["OperationsAccessResponse"];

async function request<T>(
  path: string,
  init: RequestInit = {},
  acceptedStatuses: number[] = [],
): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...init.headers,
    },
  });
  if (!response.ok && !acceptedStatuses.includes(response.status)) {
    const payload = (await response.json().catch(() => null)) as {
      detail?: { code?: string; message?: string } | string;
    } | null;
    const detail = payload?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : (detail?.message ?? detail?.code ?? "后台任务操作失败");
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export function listOperationalTasks(
  workspaceId: string,
  filters: {
    taskType?: string;
    status?: string;
    createdAfter?: string;
    createdBefore?: string;
    offset?: number;
  } = {},
) {
  const query = new URLSearchParams();
  if (filters.taskType) query.set("task_type", filters.taskType);
  if (filters.status) query.set("status", filters.status);
  if (filters.createdAfter) {
    query.set("created_after", new Date(filters.createdAfter).toISOString());
  }
  if (filters.createdBefore) {
    query.set("created_before", new Date(filters.createdBefore).toISOString());
  }
  if (filters.offset) query.set("offset", String(filters.offset));
  const suffix = query.size > 0 ? `?${query}` : "";
  return request<TaskListResponse>(
    `/v1/workspaces/${workspaceId}/operations/tasks${suffix}`,
  );
}

export function readOperationsReadiness() {
  return request<ReadinessResponse>("/health/ready", {}, [503]);
}

export function readOperationsAccess(workspaceId: string) {
  return request<OperationsAccessResponse>(
    `/v1/workspaces/${workspaceId}/operations/access`,
  );
}

export function mutateOperationalTask(
  workspaceId: string,
  task: OperationalTask,
  action: "cancel" | "retry",
  csrfToken: string,
  idempotencyKey: string,
) {
  return request<OperationalTask>(
    `/v1/workspaces/${workspaceId}/operations/tasks/${task.task_type}/${task.task_id}/${action}`,
    {
      method: "POST",
      headers: {
        "X-CSRF-Token": csrfToken,
        "Idempotency-Key": idempotencyKey,
      },
    },
  );
}
