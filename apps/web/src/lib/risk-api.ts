import type { components } from "@operations-ai/shared-schemas";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type RiskScanInputData = components["schemas"]["RiskScanInput"];
export type RiskScanData = components["schemas"]["RiskScanRead"];

async function riskRequest<T>(
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
      detail?: string | { code?: string };
    } | null;
    const detail = payload?.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : detail?.code ?? "风险扫描请求失败",
    );
  }
  return response.json() as Promise<T>;
}

export function triggerRiskScan(
  workspaceId: string,
  data: RiskScanInputData,
  csrfToken: string,
) {
  return riskRequest<RiskScanData>(
    `/v1/workspaces/${workspaceId}/risk-scans`,
    {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
      body: JSON.stringify(data),
    },
  );
}

export function readRiskScan(workspaceId: string, scanId: string) {
  return riskRequest<RiskScanData>(
    `/v1/workspaces/${workspaceId}/risk-scans/${scanId}`,
  );
}

export function listRiskScans(workspaceId: string, contentId: string) {
  const query = new URLSearchParams({ content_id: contentId });
  return riskRequest<RiskScanData[]>(
    `/v1/workspaces/${workspaceId}/risk-scans?${query}`,
  );
}
