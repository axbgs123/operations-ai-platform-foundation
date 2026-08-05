import {
  createApiClient,
  type components,
} from "@operations-ai/shared-schemas";

import { createIdempotencyKey } from "./idempotency-key";


const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type AgentBriefingData = components["schemas"]["DailyBriefingRead"];
export type AgentPlanData = components["schemas"]["AgentPlanRead"];
export type AgentRunData = components["schemas"]["AgentRunRead"];
export type AgentConfirmationData =
  components["schemas"]["AgentConfirmationRead"];
export type AgentPlanCreate = components["schemas"]["AgentPlanCreate"];
export type AgentAccount = {
  account_id: string;
  name: string;
  platform: "douyin" | "xiaohongshu";
};
export type AgentWorkspaceFixture = {
  accounts: AgentAccount[];
  briefing: AgentBriefingData;
  plan?: AgentPlanData;
  run?: AgentRunData;
  confirmations: AgentConfirmationData[];
};

export class AgentApiError extends Error {
  constructor(readonly status: number) {
    super("运营智能体请求失败");
    this.name = "AgentApiError";
  }
}

function csrfHeaders(csrfToken: string): { "X-CSRF-Token": string } {
  return { "X-CSRF-Token": csrfToken };
}

export async function loadAgentBriefing(
  workspaceId: string,
  signal?: AbortSignal,
): Promise<AgentBriefingData> {
  const { data, response } = await createApiClient(API_URL).GET(
    "/v1/workspaces/{workspace_id}/agent/briefing",
    { params: { path: { workspace_id: workspaceId } }, signal },
  );
  if (!response.ok || !data) throw new AgentApiError(response.status);
  return data;
}

export async function createAgentPlan(
  workspaceId: string,
  body: AgentPlanCreate,
  csrfToken: string,
): Promise<AgentPlanData> {
  const { data, response } = await createApiClient(API_URL).POST(
    "/v1/workspaces/{workspace_id}/agent/plans",
    {
      params: {
        path: { workspace_id: workspaceId },
        header: {
          "X-CSRF-Token": csrfToken,
          "Idempotency-Key": createIdempotencyKey("agent-plan"),
        },
      },
      body,
    },
  );
  if (!response.ok || !data) throw new AgentApiError(response.status);
  return data;
}

export async function loadAgentPlan(
  workspaceId: string,
  planId: string,
  signal?: AbortSignal,
): Promise<AgentPlanData> {
  const { data, response } = await createApiClient(API_URL).GET(
    "/v1/workspaces/{workspace_id}/agent/plans/{plan_id}",
    {
      params: { path: { workspace_id: workspaceId, plan_id: planId } },
      signal,
    },
  );
  if (!response.ok || !data) throw new AgentApiError(response.status);
  return data;
}

async function planDecision(
  workspaceId: string,
  planId: string,
  decision: "approve" | "reject",
  csrfToken: string,
): Promise<AgentPlanData> {
  const client = createApiClient(API_URL);
  const request = decision === "approve"
    ? client.POST("/v1/workspaces/{workspace_id}/agent/plans/{plan_id}/approve", {
        params: {
          path: { workspace_id: workspaceId, plan_id: planId },
          header: csrfHeaders(csrfToken),
        },
      })
    : client.POST("/v1/workspaces/{workspace_id}/agent/plans/{plan_id}/reject", {
        params: {
          path: { workspace_id: workspaceId, plan_id: planId },
          header: csrfHeaders(csrfToken),
        },
      });
  const { data, response } = await request;
  if (!response.ok || !data) throw new AgentApiError(response.status);
  return data;
}

export const approveAgentPlan = (
  workspaceId: string,
  planId: string,
  csrfToken: string,
) => planDecision(workspaceId, planId, "approve", csrfToken);

export const rejectAgentPlan = (
  workspaceId: string,
  planId: string,
  csrfToken: string,
) => planDecision(workspaceId, planId, "reject", csrfToken);

export async function startAgentRun(
  workspaceId: string,
  planId: string,
  csrfToken: string,
): Promise<AgentRunData> {
  const { data, response } = await createApiClient(API_URL).POST(
    "/v1/workspaces/{workspace_id}/agent/plans/{plan_id}/runs",
    {
      params: {
        path: { workspace_id: workspaceId, plan_id: planId },
        header: csrfHeaders(csrfToken),
      },
    },
  );
  if (!response.ok || !data) throw new AgentApiError(response.status);
  return data;
}

export async function loadAgentRuns(
  workspaceId: string,
  signal?: AbortSignal,
): Promise<AgentRunData[]> {
  const { data, response } = await createApiClient(API_URL).GET(
    "/v1/workspaces/{workspace_id}/agent/runs",
    { params: { path: { workspace_id: workspaceId } }, signal },
  );
  if (!response.ok || !data) throw new AgentApiError(response.status);
  return data.items;
}

export async function loadAgentRun(
  workspaceId: string,
  runId: string,
  signal?: AbortSignal,
): Promise<AgentRunData> {
  const { data, response } = await createApiClient(API_URL).GET(
    "/v1/workspaces/{workspace_id}/agent/runs/{run_id}",
    {
      params: { path: { workspace_id: workspaceId, run_id: runId } },
      signal,
    },
  );
  if (!response.ok || !data) throw new AgentApiError(response.status);
  return data;
}

export async function loadAgentConfirmations(
  workspaceId: string,
  signal?: AbortSignal,
): Promise<{ items: AgentConfirmationData[] }> {
  const { data, response } = await createApiClient(API_URL).GET(
    "/v1/workspaces/{workspace_id}/agent/confirmations",
    { params: { path: { workspace_id: workspaceId } }, signal },
  );
  if (!response.ok || !data) throw new AgentApiError(response.status);
  return data;
}

export async function decideAgentConfirmation(
  workspaceId: string,
  confirmation: AgentConfirmationData,
  decision: "approve" | "reject",
  csrfToken: string,
): Promise<AgentConfirmationData> {
  const { data, response } = await createApiClient(API_URL).POST(
    "/v1/workspaces/{workspace_id}/agent/runs/{run_id}/confirmations",
    {
      params: {
        path: {
          workspace_id: workspaceId,
          run_id: confirmation.run_id,
        },
        header: csrfHeaders(csrfToken),
      },
      body: {
        confirmation_id: confirmation.id,
        action_fingerprint: confirmation.action_fingerprint,
        decision,
      },
    },
  );
  if (!response.ok || !data) throw new AgentApiError(response.status);
  return data;
}

export async function recordBriefingDecision(
  workspaceId: string,
  briefing: AgentBriefingData,
  decision: "defer" | "suppress_kind",
  csrfToken: string,
): Promise<AgentBriefingData> {
  const { data, response } = await createApiClient(API_URL).POST(
    "/v1/workspaces/{workspace_id}/agent/briefings/{briefing_id}/decisions",
    {
      params: {
        path: {
          workspace_id: workspaceId,
          briefing_id: briefing.id,
        },
        header: {
          "X-CSRF-Token": csrfToken,
          "Idempotency-Key": createIdempotencyKey("agent-briefing"),
        },
      },
      body: {
        decision,
        candidate_kind: decision === "suppress_kind"
          ? briefing.primary?.kind
          : null,
      },
    },
  );
  if (!response.ok || !data) throw new AgentApiError(response.status);
  return data;
}
