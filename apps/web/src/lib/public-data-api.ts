import type { components } from "@operations-ai/shared-schemas";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type PublicProviderConfig = components["schemas"]["ProviderConfigRead"];
export type PublicContentBinding = components["schemas"]["ContentBindingRead"];
export type PublicCollectionJob = components["schemas"]["CollectionJobRead"];
export type CompetitorAccount = components["schemas"]["CompetitorAccountRead"];
export type CommentDemand = components["schemas"]["CommentDemandRead"];
export type PublicOperationsReport = components["schemas"]["PublicOperationsReportRead"];
export type PublicTrendSearch = components["schemas"]["PublicTrendSearchRead"];

class PublicDataApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

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
    const payload = (await response.json().catch(() => null)) as {
      detail?: string;
    } | null;
    throw new PublicDataApiError(
      payload?.detail ?? "公开数据采集请求失败",
      response.status,
    );
  }
  return response.json() as Promise<T>;
}

export function getPublicProvider(workspaceId: string) {
  return request<PublicProviderConfig | null>(
    `/v1/workspaces/${workspaceId}/public-data/provider`,
  );
}

export function savePublicProvider(
  workspaceId: string,
  csrfToken: string,
  input: {
    api_key: string;
    endpoint_region: "china" | "global";
    daily_request_limit: number;
  },
) {
  return request<PublicProviderConfig>(
    `/v1/workspaces/${workspaceId}/public-data/provider`,
    {
      method: "PUT",
      headers: { "X-CSRF-Token": csrfToken },
      body: JSON.stringify(input),
    },
  );
}

export function testPublicProvider(workspaceId: string, csrfToken: string) {
  return request<components["schemas"]["ProviderConnectionRead"]>(
    `/v1/workspaces/${workspaceId}/public-data/provider/test`,
    {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
    },
  );
}

export async function getPublicContentBinding(
  workspaceId: string,
  contentId: string,
): Promise<PublicContentBinding | null> {
  try {
    return await request<PublicContentBinding>(
      `/v1/workspaces/${workspaceId}/public-data/contents/${contentId}/binding`,
    );
  } catch (error) {
    if (error instanceof PublicDataApiError && error.status === 404) return null;
    throw error;
  }
}

export function savePublicContentBinding(
  workspaceId: string,
  contentId: string,
  csrfToken: string,
  input: {
    public_url: string;
    published_at: string;
    platform_content_id?: string | null;
  },
) {
  return request<PublicContentBinding>(
    `/v1/workspaces/${workspaceId}/public-data/contents/${contentId}/binding`,
    {
      method: "PUT",
      headers: { "X-CSRF-Token": csrfToken },
      body: JSON.stringify(input),
    },
  );
}

export function collectPublicContentNow(
  workspaceId: string,
  contentId: string,
  csrfToken: string,
) {
  return request<PublicCollectionJob>(
    `/v1/workspaces/${workspaceId}/public-data/contents/${contentId}/collect-now`,
    {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
    },
  );
}

export function getCompetitorAccounts(workspaceId: string) {
  return request<CompetitorAccount[]>(
    `/v1/workspaces/${workspaceId}/public-data/competitors`,
  );
}

export function createCompetitorAccount(
  workspaceId: string,
  csrfToken: string,
  input: {
    platform: "douyin" | "xiaohongshu";
    name: string;
    public_url: string;
    platform_account_id?: string | null;
    collection_interval_hours: number;
  },
) {
  return request<CompetitorAccount>(
    `/v1/workspaces/${workspaceId}/public-data/competitors`,
    {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
      body: JSON.stringify(input),
    },
  );
}

export function collectCompetitorAccount(
  workspaceId: string,
  competitorId: string,
  csrfToken: string,
) {
  return request<CompetitorAccount>(
    `/v1/workspaces/${workspaceId}/public-data/competitors/${competitorId}/collect`,
    {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
    },
  );
}

export function getCommentDemands(workspaceId: string) {
  return request<CommentDemand[]>(
    `/v1/workspaces/${workspaceId}/public-data/comment-demands`,
  );
}

export function analyzeCommentDemands(
  workspaceId: string,
  csrfToken: string,
  input: {
    platform: "douyin" | "xiaohongshu";
    public_url: string;
    platform_content_id?: string | null;
  },
) {
  return request<CommentDemand>(
    `/v1/workspaces/${workspaceId}/public-data/comment-demands`,
    {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
      body: JSON.stringify(input),
    },
  );
}

export function getPublicOperationsReport(workspaceId: string) {
  return request<PublicOperationsReport>(
    `/v1/workspaces/${workspaceId}/public-data/daily-report`,
  );
}

export function getPublicTrendSearches(workspaceId: string) {
  return request<PublicTrendSearch[]>(
    `/v1/workspaces/${workspaceId}/public-data/trend-searches`,
  );
}

export function searchPublicTrends(
  workspaceId: string,
  csrfToken: string,
  input: { platform: "douyin" | "xiaohongshu"; keyword: string },
) {
  return request<PublicTrendSearch>(
    `/v1/workspaces/${workspaceId}/public-data/trend-searches`,
    {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
      body: JSON.stringify(input),
    },
  );
}
