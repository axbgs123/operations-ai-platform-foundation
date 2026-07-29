import type { components } from "@operations-ai/shared-schemas";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type ModelCatalog = components["schemas"]["ModelCatalogRead"];
export type ModelConfig = components["schemas"]["ModelConfigRead"];
export type ModelConfigInput = components["schemas"]["ModelConfigCreate"];
export type ModelUsagePolicy = components["schemas"]["ModelUsagePolicyRead"];
export type ModelUsagePolicyInput =
  components["schemas"]["ModelUsagePolicyInput"];
export type ModelUsageSummary =
  components["schemas"]["ModelUsageSummaryRead"];
export type ModelValidation = components["schemas"]["ModelValidationRead"];

async function modelRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
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
    throw new Error(payload?.detail ?? "模型配置请求失败");
  }
  return response.json() as Promise<T>;
}

export function getModelCatalog(workspaceId: string) {
  return modelRequest<ModelCatalog>(
    `/v1/workspaces/${workspaceId}/model-configs/catalog`,
  );
}

export function listModelConfigs(workspaceId: string) {
  return modelRequest<ModelConfig[]>(
    `/v1/workspaces/${workspaceId}/model-configs`,
  );
}

export function saveModelConfig(
  workspaceId: string,
  csrfToken: string,
  data: ModelConfigInput,
) {
  return modelRequest<ModelConfig>(
    `/v1/workspaces/${workspaceId}/model-configs`,
    {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
      body: JSON.stringify(data),
    },
  );
}

export function updateModelConfigStatus(
  workspaceId: string,
  configId: string,
  status: components["schemas"]["ModelConfigStatusUpdate"]["status"],
  csrfToken: string,
) {
  return modelRequest<ModelConfig>(
    `/v1/workspaces/${workspaceId}/model-configs/${configId}`,
    {
      method: "PATCH",
      headers: { "X-CSRF-Token": csrfToken },
      body: JSON.stringify({ status }),
    },
  );
}

export function getModelUsageSummary(workspaceId: string) {
  return modelRequest<ModelUsageSummary>(
    `/v1/workspaces/${workspaceId}/model-usage/summary`,
  );
}

export function listModelUsagePolicies(workspaceId: string) {
  return modelRequest<ModelUsagePolicy[]>(
    `/v1/workspaces/${workspaceId}/model-usage/policy`,
  );
}

export function saveModelUsagePolicy(
  workspaceId: string,
  csrfToken: string,
  data: ModelUsagePolicyInput,
) {
  return modelRequest<ModelUsagePolicy>(
    `/v1/workspaces/${workspaceId}/model-usage/policy`,
    {
      method: "PUT",
      headers: { "X-CSRF-Token": csrfToken },
      body: JSON.stringify(data),
    },
  );
}

export function createModelValidation(
  workspaceId: string,
  csrfToken: string,
  data: components["schemas"]["ControlledValidationRequest"],
) {
  return modelRequest<ModelValidation>(
    `/v1/workspaces/${workspaceId}/model-validations`,
    {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
      body: JSON.stringify(data),
    },
  );
}
