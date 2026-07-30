import type { components } from "@operations-ai/shared-schemas";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type ExportTask =
  components["schemas"]["ExportTaskRead"];
export type ExportTaskPage =
  components["schemas"]["ExportTaskPage"];
export type TrashItem =
  components["schemas"]["TrashItemRead"];
export type RetentionPolicy =
  components["schemas"]["RetentionPolicyRead"];
export type RestorePreview =
  components["schemas"]["RestorePreview"];
export type FullRestore =
  components["schemas"]["FullRestoreRead"];
export type WorkspaceDeletionImpact =
  components["schemas"]["WorkspaceDeletionImpact"];
export type WorkspaceDeletionConfirmation =
  components["schemas"]["ConfirmationRead"];
export type WorkspaceDeletionJob =
  components["schemas"]["DeletionJobRead"];

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...init.headers,
    },
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as
      | { detail?: string | { code?: string } }
      | null;
    const detail = payload?.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : detail?.code ?? "数据管理请求失败",
    );
  }
  return response.json() as Promise<T>;
}

export function listExportTasks(workspaceId: string, page = 1, pageSize = 20) {
  return request<ExportTaskPage>(
    `/v1/workspaces/${workspaceId}/exports?page=${page}&page_size=${pageSize}`,
  );
}

export function createExportTask(
  workspaceId: string,
  kind: "csv" | "markdown" | "json" | "zip",
  csrfToken: string,
  contentId?: string,
) {
  return request<ExportTask>(`/v1/workspaces/${workspaceId}/exports`, {
    method: "POST",
    headers: {
      "X-CSRF-Token": csrfToken,
      "Idempotency-Key": `web-${kind}-${contentId ?? "workspace"}-${Date.now()}`,
    },
    body: JSON.stringify({
      kind,
      content_id: contentId ?? null,
    }),
  });
}

export function readExportTask(workspaceId: string, taskId: string) {
  return request<ExportTask>(
    `/v1/workspaces/${workspaceId}/exports/${taskId}`,
  );
}

async function uploadRequest<T>(
  path: string,
  file: File,
  csrfToken: string,
): Promise<T> {
  const data = new FormData();
  data.append("file", file);
  const response = await fetch(`${API_URL}${path}`, {
    method: "POST",
    credentials: "include",
    headers: {
      "X-CSRF-Token": csrfToken,
      "Idempotency-Key": `web-restore-${crypto.randomUUID()}`,
    },
    body: data,
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as
      | { detail?: string | { code?: string } }
      | null;
    const detail = payload?.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : detail?.code ?? "恢复预览请求失败",
    );
  }
  return response.json() as Promise<T>;
}

export function previewJsonRestore(
  workspaceId: string,
  file: File,
  csrfToken: string,
) {
  return uploadRequest<RestorePreview>(
    `/v1/workspaces/${workspaceId}/restore-previews?mode=merge`,
    file,
    csrfToken,
  );
}

export function previewZipRestore(
  workspaceId: string,
  file: File,
  csrfToken: string,
) {
  return uploadRequest<FullRestore>(
    `/v1/workspaces/${workspaceId}/zip-restores?mode=merge`,
    file,
    csrfToken,
  );
}

export function confirmZipRestore(
  workspaceId: string,
  restore: FullRestore,
  csrfToken: string,
) {
  return request<FullRestore>(
    `/v1/workspaces/${workspaceId}/zip-restores/${restore.id}/confirm`,
    {
      method: "POST",
      headers: {
        "X-CSRF-Token": csrfToken,
        "Idempotency-Key": `web-restore-confirm-${restore.id}`,
      },
      body: JSON.stringify({
        preview_id: restore.preview_id,
        manifest_fingerprint: restore.manifest_fingerprint,
      }),
    },
  );
}

export async function readWorkspaceDeletionImpact(workspaceId: string) {
  const response = await request<{ data: WorkspaceDeletionImpact }>(
    `/v1/workspaces/${workspaceId}/deletion-impact`,
  );
  return response.data;
}

export async function requestWorkspaceDeletionConfirmation(
  workspaceId: string,
  csrfToken: string,
) {
  const response = await request<{ data: WorkspaceDeletionConfirmation }>(
    `/v1/workspaces/${workspaceId}/deletion-confirmations`,
    {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
    },
  );
  return response.data;
}

export async function confirmWorkspaceDeletion(
  workspaceId: string,
  confirmationToken: string,
  csrfToken: string,
) {
  const response = await request<{ data: WorkspaceDeletionJob }>(
    `/v1/workspaces/${workspaceId}/deletions`,
    {
      method: "POST",
      headers: {
        "X-CSRF-Token": csrfToken,
        "Idempotency-Key": `web-workspace-delete-${workspaceId}`,
      },
      body: JSON.stringify({ confirmation_token: confirmationToken }),
    },
  );
  return response.data;
}

export async function listTrash(workspaceId: string) {
  const response = await request<{ data: TrashItem[] }>(
    `/v1/workspaces/${workspaceId}/trash`,
  );
  return response.data;
}

export async function readRetentionPolicy(workspaceId: string) {
  const response = await request<{ data: RetentionPolicy }>(
    `/v1/workspaces/${workspaceId}/retention-policy`,
  );
  return response.data;
}

export function restoreTrashContent(
  workspaceId: string,
  contentId: string,
  csrfToken: string,
) {
  return request<{ data: { id: string; deleted_at: string | null } }>(
    `/v1/workspaces/${workspaceId}/trash/contents/${contentId}/restore`,
    {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
    },
  );
}
