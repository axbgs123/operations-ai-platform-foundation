import type { components } from "@operations-ai/shared-schemas";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type ExtensionCaptureTask =
  components["schemas"]["ExtensionCaptureTaskRead"];

async function read<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? "扩展识别任务请求失败");
  }
  return response.json() as Promise<T>;
}

export function readExtensionCaptureTask(taskId: string) {
  return fetch(`${API_URL}/v1/imports/capture-tasks/${taskId}`, {
    credentials: "include",
  }).then(read<ExtensionCaptureTask>);
}

export function confirmExtensionCaptureTask(
  taskId: string,
  corrections: Record<string, string>,
  csrfToken: string,
) {
  return fetch(`${API_URL}/v1/imports/capture-tasks/${taskId}/confirm`, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrfToken,
    },
    body: JSON.stringify({ corrections }),
  }).then(read<ExtensionCaptureTask>);
}
