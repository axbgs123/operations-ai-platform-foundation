import type { components } from "@operations-ai/shared-schemas";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type EffectiveAccountConfiguration =
  components["schemas"]["EffectiveConfigurationRead"];
type ConfigurationInput = components["schemas"]["ConfigurationInput"];

async function accountRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? "账号配置请求失败");
  }
  return response.json() as Promise<T>;
}

export function loadEffectiveAccountConfiguration(workspaceId: string, accountId: string) {
  return accountRequest<EffectiveAccountConfiguration>(
    `/v1/workspaces/${workspaceId}/accounts/${accountId}/effective-configuration`,
  );
}

export function saveAccountConfiguration(
  workspaceId: string,
  accountId: string,
  csrfToken: string,
  data: ConfigurationInput,
) {
  return accountRequest(
    `/v1/workspaces/${workspaceId}/accounts/${accountId}/configuration`,
    {
      method: "PATCH",
      headers: { "X-CSRF-Token": csrfToken },
      body: JSON.stringify(data),
    },
  );
}
