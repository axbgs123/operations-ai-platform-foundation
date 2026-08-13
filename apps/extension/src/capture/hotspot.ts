import type { components } from "@operations-ai/shared-schemas";

import type { CaptureTaskRead } from "./task-status";
import { boundedJsonFetch } from "./request";

type HotspotCapture = components["schemas"]["HotspotCaptureRead"];

const mappedTask = (capture: HotspotCapture, webOrigin: string): CaptureTaskRead => ({
  task_id: capture.id,
  workspace_id: capture.workspace_id,
  platform: capture.target_platform,
  page_version: "hotspot-public-page-v1",
  status: capture.status === "review_ready" || capture.status === "confirmed" ? "succeeded"
    : capture.status === "queued" || capture.status === "running" || capture.status === "failed" ? capture.status
    : "failed",
  request_id: capture.id,
  review_url: `${webOrigin}/workspaces/${capture.workspace_id}/hotspots?capture_id=${capture.id}`,
  expires_at: capture.expires_at,
  recognition: capture.candidates === null ? null : { hotspot_candidates: capture.candidates },
  formal_snapshot_ids: capture.confirmed_snapshot_id ? [capture.confirmed_snapshot_id] : [],
  error: capture.error_code,
  provider_mode: capture.provider_mode,
  region: null,
  capture_metadata: { completeness: capture.completeness },
});

type CommonArgs = {
  serverOrigin: string;
  webOrigin: string;
  accessToken: string;
  workspaceId: string;
  onRebindRequired(): Promise<void>;
  fetcher?: typeof fetch;
};

export async function uploadHotspotCapture(args: CommonArgs & {
  platform: "douyin" | "xiaohongshu";
  screenshotDataUrl: string;
  idempotencyKey: string;
  collectedAt: string;
  sourceUrl: string;
  pageTitle: string;
  complete: boolean;
  captureMode: "full-page" | "visible" | "region";
}): Promise<CaptureTaskRead> {
  const result = await boundedJsonFetch<HotspotCapture>(
    `${args.serverOrigin}/v1/extension/workspaces/${args.workspaceId}/hotspots/captures`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${args.accessToken}`,
        "Content-Type": "application/json",
        "Idempotency-Key": args.idempotencyKey,
      },
      body: JSON.stringify({
        target_platform: args.platform,
        source_url: args.sourceUrl,
        page_title: args.pageTitle,
        collected_at: args.collectedAt,
        completeness: args.captureMode === "full-page"
          ? (args.complete ? "full_page_complete" : "full_page_partial")
          : "visible",
        screenshot_data_url: args.screenshotDataUrl,
      }),
    },
    { fetcher: args.fetcher },
  );
  if (result.response.status === 401 || result.response.status === 403) {
    await args.onRebindRequired();
    throw new Error("rebind-required");
  }
  if (!result.response.ok || !result.body) throw new Error("hotspot capture upload failed");
  return mappedTask(result.body, args.webOrigin);
}

export async function pollHotspotCapture(args: CommonArgs & { captureId: string }): Promise<CaptureTaskRead> {
  const result = await boundedJsonFetch<HotspotCapture>(
    `${args.serverOrigin}/v1/extension/workspaces/${args.workspaceId}/hotspots/captures/${args.captureId}`,
    { headers: { Authorization: `Bearer ${args.accessToken}` } },
    { fetcher: args.fetcher },
  );
  if (result.response.status === 401 || result.response.status === 403) {
    await args.onRebindRequired();
    throw new Error("rebind-required");
  }
  if (!result.response.ok || !result.body) throw new Error("hotspot capture status unavailable");
  return mappedTask(result.body, args.webOrigin);
}
