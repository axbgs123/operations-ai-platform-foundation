import type { components } from "@operations-ai/shared-schemas";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type ImportBatchData = components["schemas"]["ImportBatchRead"];
export type ImportConfirmationData = components["schemas"]["ImportConfirmationRead"];
type ManualPreviewRequest = components["schemas"]["ManualPreviewRequest"];

async function readResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      detail?: string;
    } | null;
    throw new Error(payload?.detail ?? "导入请求失败");
  }
  return response.json() as Promise<T>;
}

async function importRequest<T>(path: string, init: RequestInit): Promise<T> {
  return readResponse<T>(
    await fetch(`${API_URL}${path}`, {
      ...init,
      credentials: "include",
      headers: { "Content-Type": "application/json", ...init.headers },
    }),
  );
}

export async function previewTabularImport(
  workspaceId: string,
  accountId: string,
  platform: "douyin" | "xiaohongshu",
  contentType: "video" | "image_text",
  file: File,
  csrfToken: string,
) {
  const form = new FormData();
  form.set("account_id", accountId);
  form.set("platform", platform);
  form.set("content_type", contentType);
  form.set("file", file);
  return readResponse<ImportBatchData>(
    await fetch(`${API_URL}/v1/workspaces/${workspaceId}/imports/tabular/preview`, {
      method: "POST",
      credentials: "include",
      headers: { "X-CSRF-Token": csrfToken },
      body: form,
    }),
  );
}

export function previewManualImport(
  workspaceId: string,
  data: ManualPreviewRequest,
  csrfToken: string,
) {
  return importRequest<ImportBatchData>(
    `/v1/workspaces/${workspaceId}/imports/manual/preview`,
    {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
      body: JSON.stringify(data),
    },
  );
}

export function updateImportMapping(
  batchId: string,
  mapping: Record<string, string>,
  csrfToken: string,
) {
  return importRequest<ImportBatchData>(`/v1/imports/${batchId}/mapping`, {
    method: "PATCH",
    headers: { "X-CSRF-Token": csrfToken },
    body: JSON.stringify({ mapping }),
  });
}

export function updateImportRow(
  batchId: string,
  rowId: string,
  changes: Record<string, unknown>,
  csrfToken: string,
) {
  return importRequest<ImportBatchData>(
    `/v1/imports/${batchId}/rows/${rowId}`,
    {
      method: "PATCH",
      headers: { "X-CSRF-Token": csrfToken },
      body: JSON.stringify({ changes }),
    },
  );
}

export function confirmImport(
  batchId: string,
  selectedRowIds: string[],
  csrfToken: string,
) {
  return importRequest<ImportConfirmationData>(`/v1/imports/${batchId}/confirm`, {
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
    body: JSON.stringify({ selected_row_ids: selectedRowIds }),
  });
}
