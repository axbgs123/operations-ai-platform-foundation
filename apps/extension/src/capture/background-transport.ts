import type { components } from "@operations-ai/shared-schemas";

import type { CaptureState } from "../content/overlay";
import type {
  CaptureCompletionMetadata,
  CaptureContext,
  PollCaptureTaskMessage,
  PollHotspotCaptureMessage,
  UploadCaptureTaskMessage,
  UploadHotspotCaptureMessage,
} from "../runtime/messages";

type CaptureTask = components["schemas"]["ExtensionCaptureTaskRead"];
type SendMessage = (message: UploadCaptureTaskMessage | PollCaptureTaskMessage) => Promise<unknown>;
type HotspotSendMessage = (message: UploadHotspotCaptureMessage | PollHotspotCaptureMessage) => Promise<unknown>;

type UploadController = {
  state: CaptureState;
  preview: { imageData: string; maskedRegions: unknown[] } | null;
  canUpload(): boolean;
};

type BackgroundTaskResponse =
  | { ok: true; task: CaptureTask }
  | { ok: false; error: string };

const parseResponse = (value: unknown): BackgroundTaskResponse | null => {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const response = value as Record<string, unknown>;
  if (
    response.ok === false &&
    typeof response.error === "string" &&
    Object.keys(response).sort().join(",") === "error,ok"
  ) {
    return { ok: false, error: response.error };
  }
  if (
    response.ok !== true ||
    typeof response.task !== "object" ||
    response.task === null ||
    Array.isArray(response.task) ||
    Object.keys(response).sort().join(",") !== "ok,task"
  ) {
    return null;
  }
  const task = response.task as Record<string, unknown>;
  if (typeof task.task_id !== "string" || typeof task.status !== "string") return null;
  return { ok: true, task: response.task as CaptureTask };
};

const taskFromResponse = (value: unknown) => {
  const response = parseResponse(value);
  if (!response) throw new Error("capture response invalid");
  if (!response.ok) throw new Error(response.error);
  return response.task;
};

export async function uploadCaptureThroughBackground(args: {
  controller: UploadController;
  collectedAt: string;
  idempotencyKey: string;
  captureMetadata: CaptureCompletionMetadata;
  sendMessage: SendMessage;
} & CaptureContext): Promise<CaptureTask> {
  if (!args.controller.canUpload() || args.controller.state !== "preview_ready") {
    throw new Error("preview_ready is required before upload");
  }
  const screenshotDataUrl = args.controller.preview?.imageData;
  if (!screenshotDataUrl) throw new Error("final preview is unavailable");
  return taskFromResponse(await args.sendMessage({
    type: "UPLOAD_CAPTURE_TASK",
    platform: args.platform,
    pageVersion: args.pageVersion,
    pageSignature: args.pageSignature,
    screenshotDataUrl,
    collectedAt: args.collectedAt,
    idempotencyKey: args.idempotencyKey,
    captureMetadata: args.captureMetadata,
  }));
}

export async function pollCaptureThroughBackground(args: {
  taskId: string;
  sendMessage: SendMessage;
} & CaptureContext): Promise<CaptureTask> {
  return taskFromResponse(await args.sendMessage({
    type: "POLL_CAPTURE_TASK",
    platform: args.platform,
    pageVersion: args.pageVersion,
    pageSignature: args.pageSignature,
    taskId: args.taskId,
  }));
}

export async function uploadHotspotThroughBackground(args: {
  controller: UploadController;
  collectedAt: string;
  idempotencyKey: string;
  sourceUrl: string;
  pageTitle: string;
  captureMetadata: CaptureCompletionMetadata;
  sendMessage: HotspotSendMessage;
} & CaptureContext): Promise<CaptureTask> {
  if (!args.controller.canUpload() || args.controller.state !== "preview_ready") {
    throw new Error("preview_ready is required before upload");
  }
  const screenshotDataUrl = args.controller.preview?.imageData;
  if (!screenshotDataUrl) throw new Error("final preview is unavailable");
  return taskFromResponse(await args.sendMessage({
    type: "UPLOAD_HOTSPOT_CAPTURE",
    platform: args.platform,
    pageVersion: args.pageVersion,
    pageSignature: args.pageSignature,
    screenshotDataUrl,
    collectedAt: args.collectedAt,
    idempotencyKey: args.idempotencyKey,
    sourceUrl: args.sourceUrl,
    pageTitle: args.pageTitle,
    captureMetadata: args.captureMetadata,
  }));
}

export async function pollHotspotThroughBackground(args: {
  captureId: string;
  sendMessage: HotspotSendMessage;
} & CaptureContext): Promise<CaptureTask> {
  return taskFromResponse(await args.sendMessage({
    type: "POLL_HOTSPOT_CAPTURE",
    platform: args.platform,
    pageVersion: args.pageVersion,
    pageSignature: args.pageSignature,
    captureId: args.captureId,
  }));
}
