import {
  createApiClient,
  type components,
} from "@operations-ai/shared-schemas";


const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type WorkbenchContext =
  components["schemas"]["WorkbenchContextRead"];

export class WorkbenchApiError extends Error {
  constructor(readonly status: number) {
    super("workbench request failed");
    this.name = "WorkbenchApiError";
  }
}

export async function loadWorkbenchContext(
  workspaceId: string,
  signal?: AbortSignal,
): Promise<WorkbenchContext> {
  const client = createApiClient(API_URL);
  const { data, response } = await client.GET(
    "/v1/workspaces/{workspace_id}/workbench/context",
    {
      params: { path: { workspace_id: workspaceId } },
      signal,
    },
  );
  if (!response.ok || !data) {
    throw new WorkbenchApiError(response.status);
  }
  return data;
}
