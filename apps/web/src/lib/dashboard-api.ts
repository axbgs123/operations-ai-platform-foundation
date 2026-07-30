import type { components } from "@operations-ai/shared-schemas";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type DashboardFilter = components["schemas"]["DrillDownFilter"];
export type DashboardChart = components["schemas"]["DashboardChart"];
export type AccountDashboardData = components["schemas"]["AccountDashboard"];
export type DashboardContentItem = components["schemas"]["DashboardContentItem"];

export class DashboardApiError extends Error {
  constructor(readonly status: number) {
    super("dashboard request failed");
    this.name = "DashboardApiError";
  }
}

export async function loadAccountDashboard(
  workspaceId: string,
  accountId: string,
  contentType: "video" | "image_text" = "image_text",
  maturityBucket: DashboardFilter["maturity_bucket"] = "24h",
) {
  const query = new URLSearchParams({
    content_type: contentType,
    maturity_bucket: maturityBucket,
  });
  const response = await fetch(
    `${API_URL}/v1/workspaces/${workspaceId}/accounts/${accountId}/dashboard?${query}`,
    { credentials: "include" },
  );
  if (!response.ok) throw new DashboardApiError(response.status);
  return response.json() as Promise<AccountDashboardData>;
}

export function dashboardDrillDownHref(filter: DashboardFilter) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(filter)) {
    if (Array.isArray(value)) {
      value.forEach((item) => query.append(key, item));
    } else if (value != null) {
      query.set(key, value);
    }
  }
  return `/workspaces/${filter.workspace_id}/contents?${query}`;
}

export async function loadDashboardContents(filter: DashboardFilter) {
  const query = new URLSearchParams({
    content_type: filter.content_type,
    maturity_bucket: filter.maturity_bucket,
  });
  if (filter.metric_key) query.set("metric_key", filter.metric_key);
  (filter.required_metric_keys ?? []).forEach((key) => {
    query.append("required_metric_keys", key);
  });
  if (filter.attention) query.set("attention", filter.attention);
  const response = await fetch(
    `${API_URL}/v1/workspaces/${filter.workspace_id}/accounts/${filter.account_id}/dashboard/contents?${query}`,
    { credentials: "include" },
  );
  if (!response.ok) throw new Error("下钻内容加载失败");
  return response.json() as Promise<DashboardContentItem[]>;
}
