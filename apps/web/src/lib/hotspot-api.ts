import { createApiClient, type components } from "@operations-ai/shared-schemas";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export type HotspotCapture = components["schemas"]["HotspotCaptureRead"];
export type HotspotSnapshot = components["schemas"]["HotspotSnapshotRead"];

export async function loadHotspotCapture(workspaceId: string, captureId: string): Promise<HotspotCapture> {
  const { data, response } = await createApiClient(API_URL).GET(
    "/v1/workspaces/{workspace_id}/hotspots/captures/{capture_id}",
    { params: { path: { workspace_id: workspaceId, capture_id: captureId } } },
  );
  if (!response.ok || !data) throw new Error("热点截图读取失败");
  return data;
}

export async function confirmHotspotCapture(
  workspaceId: string,
  captureId: string,
  entries: HotspotCapture["candidates"],
  csrfToken: string,
): Promise<HotspotSnapshot> {
  const { data, response } = await createApiClient(API_URL).POST(
    "/v1/workspaces/{workspace_id}/hotspots/captures/{capture_id}/confirm",
    {
      params: {
        path: { workspace_id: workspaceId, capture_id: captureId },
        header: { "X-CSRF-Token": csrfToken },
      },
      body: { entries: entries.map(({ topic, rank, heat }) => ({ topic, rank, heat, selected: true })) },
    },
  );
  if (!response.ok || !data) throw new Error("热点确认失败");
  return data;
}
