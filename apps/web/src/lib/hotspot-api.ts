import { createApiClient, type components } from "@operations-ai/shared-schemas";

import { createIdempotencyKey } from "./idempotency-key";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export type HotspotCapture = components["schemas"]["HotspotCaptureRead"];
export type HotspotSnapshot = components["schemas"]["HotspotSnapshotRead"];
export type HotspotResearch = components["schemas"]["HotspotResearchRead"];

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

export async function loadHotspotSnapshots(workspaceId: string): Promise<HotspotSnapshot[]> {
  const { data, response } = await createApiClient(API_URL).GET(
    "/v1/workspaces/{workspace_id}/hotspots/snapshots",
    { params: { path: { workspace_id: workspaceId } } },
  );
  if (!response.ok || !data) throw new Error("热点快照读取失败");
  return data;
}

export async function loadHotspotResearch(workspaceId: string): Promise<HotspotResearch[]> {
  const { data, response } = await createApiClient(API_URL).GET(
    "/v1/workspaces/{workspace_id}/hotspots/research",
    { params: { path: { workspace_id: workspaceId } } },
  );
  if (!response.ok || !data) throw new Error("热点研究记录读取失败");
  return data;
}

export async function researchHotspot(
  workspaceId: string,
  snapshotId: string,
  accountId: string,
  csrfToken: string,
): Promise<HotspotResearch> {
  const { data, response } = await createApiClient(API_URL).POST(
    "/v1/workspaces/{workspace_id}/hotspots/snapshots/{snapshot_id}/research",
    {
      params: {
        path: { workspace_id: workspaceId, snapshot_id: snapshotId },
        header: {
          "X-CSRF-Token": csrfToken,
          "Idempotency-Key": createIdempotencyKey("hotspot-research"),
        },
      },
      body: { account_id: accountId },
    },
  );
  if (!response.ok || !data) throw new Error("联网核实失败，请检查模型联网状态和用量设置");
  return data;
}

export async function saveHotspotCandidate(
  workspaceId: string,
  researchId: string,
  candidateIndex: number,
  csrfToken: string,
): Promise<HotspotResearch> {
  const { data, response } = await createApiClient(API_URL).POST(
    "/v1/workspaces/{workspace_id}/hotspots/research/{research_id}/save-candidate",
    {
      params: {
        path: { workspace_id: workspaceId, research_id: researchId },
        header: { "X-CSRF-Token": csrfToken },
      },
      body: { candidate_index: candidateIndex },
    },
  );
  if (!response.ok || !data) throw new Error("保存内容草稿失败");
  return data;
}
