import type { components } from "@operations-ai/shared-schemas";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type AnalysisRunData = components["schemas"]["AnalysisRunRead"];
export type AnalysisSuggestionData = components["schemas"]["AnalysisSuggestionRead"];
export type ProductEventAck = components["schemas"]["ProductEventAck"];

async function analysisRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...init.headers },
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? "深度分析请求失败");
  }
  return response.json() as Promise<T>;
}

export function requestContentAnalysis(contentId: string, csrfToken: string) {
  return analysisRequest<AnalysisRunData>(`/v1/contents/${contentId}/analysis-runs`, {
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
  });
}

export function readAnalysisRun(contentId: string, runId: string) {
  return analysisRequest<AnalysisRunData>(`/v1/contents/${contentId}/analysis-runs/${runId}`);
}

export function markAnalysisViewed(
  contentId: string,
  runId: string,
  csrfToken: string,
) {
  return analysisRequest<ProductEventAck>(
    `/v1/contents/${contentId}/analysis-runs/${runId}/view`,
    {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
    },
  );
}

export function createAnalysisFeedback(
  contentId: string,
  runId: string,
  rating: "useful" | "not_useful",
  csrfToken: string,
  idempotencyKey: string,
) {
  return analysisRequest<ProductEventAck>(
    `/v1/contents/${contentId}/analysis-runs/${runId}/feedback`,
    {
      method: "POST",
      headers: {
        "X-CSRF-Token": csrfToken,
        "Idempotency-Key": idempotencyKey,
      },
      body: JSON.stringify({ rating }),
    },
  );
}

export function saveAnalysisSuggestion(
  contentId: string,
  runId: string,
  recommendationId: string,
  csrfToken: string,
) {
  return analysisRequest<AnalysisSuggestionData>(
    `/v1/contents/${contentId}/analysis-runs/${runId}/suggestions/${recommendationId}`,
    { method: "POST", headers: { "X-CSRF-Token": csrfToken } },
  );
}

export function updateAnalysisSuggestion(
  contentId: string,
  suggestionId: string,
  adoptionStatus: "adopted" | "rejected",
  csrfToken: string,
) {
  return analysisRequest<AnalysisSuggestionData>(
    `/v1/contents/${contentId}/analysis-suggestions/${suggestionId}`,
    {
      method: "PATCH",
      headers: { "X-CSRF-Token": csrfToken },
      body: JSON.stringify({ adoption_status: adoptionStatus }),
    },
  );
}
