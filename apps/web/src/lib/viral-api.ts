import type { components } from "@operations-ai/shared-schemas";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type ViralCandidateData = components["schemas"]["ViralCandidateRead"];
export type ViralConfirmationData = components["schemas"]["ViralConfirmationInput"];
export type ViralLibraryItemData = components["schemas"]["ViralLibraryItemRead"];
export type ViralThresholdData = components["schemas"]["ViralThresholdRead"];
export type ViralThresholdInput = components["schemas"]["ViralThresholdInput"];
export type ViralEvaluationInput = components["schemas"]["ViralEvaluationInput"];

async function viralRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...init.headers },
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      detail?: string;
    } | null;
    throw new Error(payload?.detail ?? "爆款素材请求失败");
  }
  return response.json() as Promise<T>;
}

export function listViralCandidates(workspaceId: string, accountId: string) {
  const query = new URLSearchParams({ account_id: accountId });
  return viralRequest<ViralCandidateData[]>(
    `/v1/workspaces/${workspaceId}/viral-candidates?${query}`,
  );
}

export function listViralLibrary(workspaceId: string, accountId: string) {
  const query = new URLSearchParams({ account_id: accountId });
  return viralRequest<ViralLibraryItemData[]>(
    `/v1/workspaces/${workspaceId}/viral-library?${query}`,
  );
}

export function readViralThresholds(workspaceId: string, accountId: string) {
  return viralRequest<ViralThresholdData | null>(
    `/v1/workspaces/${workspaceId}/accounts/${accountId}/viral-thresholds`,
  );
}

export function configureViralThresholds(
  workspaceId: string,
  accountId: string,
  data: ViralThresholdInput,
  csrfToken: string,
) {
  return viralRequest<ViralThresholdData>(
    `/v1/workspaces/${workspaceId}/accounts/${accountId}/viral-thresholds`,
    {
      method: "PUT",
      headers: { "X-CSRF-Token": csrfToken },
      body: JSON.stringify(data),
    },
  );
}

export function evaluateViralCandidates(
  workspaceId: string,
  accountId: string,
  data: ViralEvaluationInput,
  csrfToken: string,
) {
  return viralRequest<ViralCandidateData[]>(
    `/v1/workspaces/${workspaceId}/accounts/${accountId}/viral-candidates/evaluate`,
    {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
      body: JSON.stringify(data),
    },
  );
}

export function confirmViralCandidate(
  workspaceId: string,
  candidateId: string,
  data: ViralConfirmationData,
  csrfToken: string,
) {
  return viralRequest<ViralLibraryItemData>(
    `/v1/workspaces/${workspaceId}/viral-candidates/${candidateId}/confirm`,
    {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
      body: JSON.stringify(data),
    },
  );
}

export function revokeViralLibraryItem(
  workspaceId: string,
  itemId: string,
  reason: string,
  csrfToken: string,
) {
  return viralRequest<ViralLibraryItemData>(
    `/v1/workspaces/${workspaceId}/viral-library/${itemId}/revoke`,
    {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
      body: JSON.stringify({ reason }),
    },
  );
}
