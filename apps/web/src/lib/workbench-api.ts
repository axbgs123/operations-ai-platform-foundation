import {
  createApiClient,
  type components,
  type operations,
} from "@operations-ai/shared-schemas";


const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type WorkbenchContext =
  components["schemas"]["WorkbenchContextRead"];
export type WorkbenchOverviewData =
  components["schemas"]["WorkbenchOverviewRead"];
export type PreflightQueuePageData =
  components["schemas"]["PreflightQueueRead"];
type WorkbenchOverviewOperation =
  operations["read_workbench_overview_v1_workspaces__workspace_id__workbench_overview_get"];
export type WorkbenchOverviewScope = NonNullable<
  WorkbenchOverviewOperation["parameters"]["query"]
>;
type PreflightQueueOperation =
  operations["read_preflight_queue_v1_workspaces__workspace_id__workbench_preflight_queue_get"];
export type PreflightQueueApiQuery = NonNullable<
  PreflightQueueOperation["parameters"]["query"]
>;

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

export async function loadWorkbenchOverview(
  workspaceId: string,
  signal?: AbortSignal,
  scope: WorkbenchOverviewScope = {},
): Promise<WorkbenchOverviewData> {
  const client = createApiClient(API_URL);
  const { data, response } = await client.GET(
    "/v1/workspaces/{workspace_id}/workbench/overview",
    {
      params: {
        path: { workspace_id: workspaceId },
        query: scope,
      },
      signal,
    },
  );
  if (!response.ok || !data) {
    throw new WorkbenchApiError(response.status);
  }
  return data;
}

export async function loadPreflightQueue(
  workspaceId: string,
  query: PreflightQueueApiQuery,
  signal?: AbortSignal,
): Promise<PreflightQueuePageData> {
  const client = createApiClient(API_URL);
  const { data, response } = await client.GET(
    "/v1/workspaces/{workspace_id}/workbench/preflight-queue",
    {
      params: {
        path: { workspace_id: workspaceId },
        query,
      },
      signal,
    },
  );
  if (!response.ok || !data) {
    throw new WorkbenchApiError(response.status);
  }
  return data;
}
