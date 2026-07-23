import type { components } from "@operations-ai/shared-schemas";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type FactSourceData = components["schemas"]["FactSourceRead"];
export type FactItemData = components["schemas"]["FactItemRead"];
export type FactContextData = components["schemas"]["FactContextRead"];
export type FactSourceInput = components["schemas"]["FactSourceCreate"];

async function factRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as
      | { detail?: string | { message?: string } }
      | null;
    const detail = payload?.detail;
    throw new Error(
      typeof detail === "string" ? detail : detail?.message ?? "事实资料请求失败",
    );
  }
  return response.json() as Promise<T>;
}

export function listFactSources(workspaceId: string) {
  return factRequest<FactSourceData[]>(`/v1/workspaces/${workspaceId}/fact-sources`);
}

export function getFactContext(workspaceId: string) {
  return factRequest<FactContextData>(`/v1/workspaces/${workspaceId}/fact-context`);
}

export function createFactSource(
  workspaceId: string,
  csrfToken: string,
  input: FactSourceInput,
) {
  return factRequest<FactSourceData>(`/v1/workspaces/${workspaceId}/fact-sources`, {
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
    body: JSON.stringify(input),
  });
}

export async function uploadFactSource(
  workspaceId: string,
  csrfToken: string,
  form: FormData,
) {
  const response = await fetch(
    `${API_URL}/v1/workspaces/${workspaceId}/fact-sources/upload`,
    {
      method: "POST",
      credentials: "include",
      headers: { "X-CSRF-Token": csrfToken },
      body: form,
    },
  );
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as
      | { detail?: string }
      | null;
    throw new Error(payload?.detail ?? "事实资料上传失败");
  }
  return response.json() as Promise<FactSourceData>;
}

export function confirmFactItem(
  workspaceId: string,
  itemId: string,
  csrfToken: string,
) {
  return factRequest<FactItemData>(
    `/v1/workspaces/${workspaceId}/fact-items/${itemId}/confirm`,
    {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
    },
  );
}
