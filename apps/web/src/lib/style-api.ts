import type { components } from "@operations-ai/shared-schemas";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type StyleCandidateData = components["schemas"]["StyleCandidateRead"];
export type StyleProfileData = components["schemas"]["StyleProfileRead"];
export type StyleSampleData = components["schemas"]["StyleSampleRead"];
export type StyleScopeData = components["schemas"]["ColumnCampaignRead"];
export type StyleProhibitedInput = {
  expressions: string[];
  colors: string[];
  layouts: string[];
  visual_styles: string[];
};

async function styleRequest<T>(path: string, init?: RequestInit): Promise<T> {
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
      typeof detail === "string" ? detail : detail?.message ?? "风格档案请求失败",
    );
  }
  return response.json() as Promise<T>;
}

export function listStyleCandidates(
  workspaceId: string,
  accountId: string,
  columnCampaignId: string | null = null,
) {
  const query = columnCampaignId ? `?column_campaign_id=${columnCampaignId}` : "";
  return styleRequest<StyleCandidateData[]>(
    `/v1/workspaces/${workspaceId}/accounts/${accountId}/style-samples/candidates${query}`,
  );
}

export function listStyleSamples(
  workspaceId: string,
  accountId: string,
  columnCampaignId: string | null = null,
) {
  const query = columnCampaignId ? `?column_campaign_id=${columnCampaignId}` : "";
  return styleRequest<StyleSampleData[]>(
    `/v1/workspaces/${workspaceId}/accounts/${accountId}/style-samples${query}`,
  );
}

export function listStyleProfiles(workspaceId: string, accountId: string) {
  return styleRequest<StyleProfileData[]>(
    `/v1/workspaces/${workspaceId}/accounts/${accountId}/style-profiles`,
  );
}

export function listStyleScopes(workspaceId: string, accountId: string) {
  return styleRequest<StyleScopeData[]>(
    `/v1/workspaces/${workspaceId}/accounts/${accountId}/columns-campaigns`,
  );
}

export function selectStyleSample(
  workspaceId: string,
  accountId: string,
  contentId: string,
  csrfToken: string,
  columnCampaignId: string | null = null,
) {
  return styleRequest<StyleSampleData>(
    `/v1/workspaces/${workspaceId}/accounts/${accountId}/style-samples`,
    {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
      body: JSON.stringify({
        content_id: contentId,
        column_campaign_id: columnCampaignId,
      }),
    },
  );
}

export function extractStyleProfile(
  workspaceId: string,
  accountId: string,
  csrfToken: string,
  columnCampaignId: string | null,
  prohibited: StyleProhibitedInput,
) {
  return styleRequest<StyleProfileData>(
    `/v1/workspaces/${workspaceId}/accounts/${accountId}/style-profiles/extract`,
    {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
      body: JSON.stringify({
        column_campaign_id: columnCampaignId,
        prohibited,
      }),
    },
  );
}

export function confirmStyleProfile(
  workspaceId: string,
  profileId: string,
  csrfToken: string,
) {
  return styleRequest<StyleProfileData>(
    `/v1/workspaces/${workspaceId}/style-profiles/${profileId}/confirm`,
    {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
    },
  );
}
