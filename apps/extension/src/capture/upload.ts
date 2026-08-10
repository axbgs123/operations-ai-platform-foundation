import type { CaptureState } from "../content/overlay";
import type { components } from "@operations-ai/shared-schemas";
import { boundedJsonFetch } from "./request";

type UploadController = {
  state: CaptureState;
  preview: { imageData: string; maskedRegions: unknown[] } | null;
  canUpload(): boolean;
};

export type CaptureTaskResponse =
  components["schemas"]["ExtensionCaptureTaskRead"];

type UploadArgs = {
  controller: UploadController;
  serverOrigin: string;
  accessToken: string;
  workspaceId: string;
  platform: "douyin" | "xiaohongshu";
  pageVersion: string;
  pageIdentifier: string;
  collectedAt: string;
  fetcher?: typeof fetch;
  idempotencyKey: string;
  onRebindRequired?: () => Promise<void>;
  requestMaxAttempts?: number;
  requestTimeoutMs?: number;
  retrySleep?: (milliseconds: number) => Promise<void>;
};

export async function uploadPreview(args: UploadArgs): Promise<CaptureTaskResponse> {
  if (!args.controller.canUpload() || args.controller.state !== "preview_ready") {
    throw new Error("preview_ready is required before upload");
  }
  if (!args.controller.preview?.imageData) {
    throw new Error("final preview is unavailable");
  }
  const result = await boundedJsonFetch<CaptureTaskResponse>(
    `${args.serverOrigin}/v1/extension/workspaces/${args.workspaceId}/capture-tasks`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${args.accessToken}`,
        "Content-Type": "application/json",
        "Idempotency-Key": args.idempotencyKey,
      },
      body: JSON.stringify({
        platform: args.platform,
        page_version: args.pageVersion,
        page_identifier: args.pageIdentifier,
        collected_at: args.collectedAt,
        screenshot_data_url: args.controller.preview.imageData,
      }),
    },
    {
      fetcher: args.fetcher,
      maxAttempts: args.requestMaxAttempts,
      timeoutMs: args.requestTimeoutMs,
      retrySleep: args.retrySleep,
    },
  );
  const { response } = result;
  if (response.status === 401 || response.status === 403) {
    await args.onRebindRequired?.();
    throw new Error("rebind-required");
  }
  if (!response.ok) throw new Error("capture upload failed");
  if (!result.body) throw new Error("capture response invalid");
  return result.body;
}
