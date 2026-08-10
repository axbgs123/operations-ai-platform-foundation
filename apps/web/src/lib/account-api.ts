import type { components } from "@operations-ai/shared-schemas";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type EffectiveAccountConfiguration =
  components["schemas"]["EffectiveConfigurationRead"];
export type AccountSummary = components["schemas"]["AccountSummaryRead"];
export type AccountCreateInput = components["schemas"]["AccountCreate"];
export type AccountRead = components["schemas"]["AccountRead"];
export type ColumnCampaign = components["schemas"]["ColumnCampaignRead"];
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

export function createAccount(
  workspaceId: string,
  csrfToken: string,
  input: AccountCreateInput,
): Promise<AccountRead> {
  return accountRequest(`/v1/workspaces/${workspaceId}/accounts`, {
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
    body: JSON.stringify(input),
  });
}

export function loadColumnCampaigns(
  workspaceId: string,
  accountId: string,
): Promise<ColumnCampaign[]> {
  return accountRequest(
    `/v1/workspaces/${workspaceId}/accounts/${accountId}/columns-campaigns`,
  );
}

export function loadEffectiveColumnConfiguration(
  workspaceId: string,
  accountId: string,
  columnCampaignId: string,
): Promise<EffectiveAccountConfiguration> {
  const query = new URLSearchParams({
    column_campaign_id: columnCampaignId,
  });
  return accountRequest(
    `/v1/workspaces/${workspaceId}/accounts/${accountId}/effective-configuration?${query}`,
  );
}

export function restoreColumnDefaults(
  workspaceId: string,
  accountId: string,
  columnCampaignId: string,
  csrfToken: string,
): Promise<ColumnCampaign> {
  return accountRequest(
    `/v1/workspaces/${workspaceId}/accounts/${accountId}/columns-campaigns/${columnCampaignId}`,
    {
      method: "PATCH",
      headers: { "X-CSRF-Token": csrfToken },
      body: JSON.stringify({ restore_account_defaults: true }),
    },
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
