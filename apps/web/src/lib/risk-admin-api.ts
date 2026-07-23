import type { components } from "@operations-ai/shared-schemas";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type RiskDocumentAdminData =
  components["schemas"]["RiskDocumentRead"];
export type RiskEvaluationData =
  components["schemas"]["RiskEvaluationRead"];
export type RiskRuleCandidateData =
  components["schemas"]["RiskRuleUpdateCandidateRead"];

async function riskAdminRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...init.headers },
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as
      | { detail?: string | { code?: string } }
      | null;
    const detail = payload?.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : detail?.code ?? "风控知识请求失败",
    );
  }
  return response.json() as Promise<T>;
}

export function listRiskDocuments(
  workspaceId: string,
  platform?: "douyin" | "xiaohongshu",
) {
  const query = platform ? `?platform=${platform}` : "";
  return riskAdminRequest<RiskDocumentAdminData[]>(
    `/v1/workspaces/${workspaceId}/risk-documents${query}`,
  );
}

export function readRiskEvaluation(
  workspaceId: string,
  platform: "douyin" | "xiaohongshu",
) {
  return riskAdminRequest<RiskEvaluationData>(
    `/v1/workspaces/${workspaceId}/risk-evaluations?platform=${platform}`,
  );
}

export function transitionRiskDocument(
  workspaceId: string,
  documentId: string,
  action:
    | "submit-review"
    | "activate"
    | "reject"
    | "supersede"
    | "expire"
    | "check-update",
  csrfToken: string,
) {
  return riskAdminRequest<RiskDocumentAdminData>(
    `/v1/workspaces/${workspaceId}/risk-documents/${documentId}/${action}`,
    {
      method: "POST",
      headers: {
        "X-CSRF-Token": csrfToken,
        "Idempotency-Key": `${action}-${documentId}`,
      },
    },
  );
}

export function parseRiskDocument(
  workspaceId: string,
  documentId: string,
  csrfToken: string,
  text: string,
) {
  return riskAdminRequest<RiskDocumentAdminData>(
    `/v1/workspaces/${workspaceId}/risk-documents/${documentId}/parse`,
    {
      method: "POST",
      headers: {
        "X-CSRF-Token": csrfToken,
        "Idempotency-Key": `parse-${documentId}`,
      },
      body: JSON.stringify({ text, source_location: "后台人工输入" }),
    },
  );
}

export function listRiskFeedbackCandidates(
  workspaceId: string,
  platform: "douyin" | "xiaohongshu",
) {
  return riskAdminRequest<RiskRuleCandidateData[]>(
    `/v1/workspaces/${workspaceId}/risk-feedback/candidates?platform=${platform}`,
  );
}

export function reviewRiskFeedback(
  workspaceId: string,
  feedbackId: string,
  csrfToken: string,
  status: "approved" | "rejected",
) {
  return riskAdminRequest<components["schemas"]["RiskFeedbackRead"]>(
    `/v1/workspaces/${workspaceId}/risk-feedback/${feedbackId}/review`,
    {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
      body: JSON.stringify({ status, note: "后台人工审核" }),
    },
  );
}
