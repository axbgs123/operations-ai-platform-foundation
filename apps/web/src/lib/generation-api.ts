import type { components } from "@operations-ai/shared-schemas";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type GenerationInputs = components["schemas"]["GenerationInputs"];
export type TextGenerationRunData =
  components["schemas"]["TextGenerationRunRead"];
export type TextGenerationEdit =
  components["schemas"]["TextGenerationEdit"];

async function generationRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...init.headers },
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      detail?: string;
    } | null;
    throw new Error(payload?.detail ?? "文本生成请求失败");
  }
  return response.json() as Promise<T>;
}

export function requestTextGeneration(
  workspaceId: string,
  data: GenerationInputs,
  csrfToken: string,
) {
  return generationRequest<TextGenerationRunData>(
    `/v1/workspaces/${workspaceId}/generation/text-runs`,
    {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
      body: JSON.stringify(data),
    },
  );
}

export function readTextGeneration(workspaceId: string, runId: string) {
  return generationRequest<TextGenerationRunData>(
    `/v1/workspaces/${workspaceId}/generation/text-runs/${runId}`,
  );
}

export function editTextGeneration(
  workspaceId: string,
  runId: string,
  data: TextGenerationEdit,
  csrfToken: string,
) {
  return generationRequest<TextGenerationRunData>(
    `/v1/workspaces/${workspaceId}/generation/text-runs/${runId}`,
    {
      method: "PATCH",
      headers: { "X-CSRF-Token": csrfToken },
      body: JSON.stringify(data),
    },
  );
}

export function cancelTextGeneration(
  workspaceId: string,
  runId: string,
  csrfToken: string,
) {
  return generationRequest<TextGenerationRunData>(
    `/v1/workspaces/${workspaceId}/generation/text-runs/${runId}/cancel`,
    { method: "POST", headers: { "X-CSRF-Token": csrfToken } },
  );
}

export function retryTextGeneration(
  workspaceId: string,
  runId: string,
  csrfToken: string,
) {
  return generationRequest<TextGenerationRunData>(
    `/v1/workspaces/${workspaceId}/generation/text-runs/${runId}/retry`,
    { method: "POST", headers: { "X-CSRF-Token": csrfToken } },
  );
}
