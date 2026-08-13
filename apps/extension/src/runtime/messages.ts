export type GetPageStatusMessage = { type: "GET_PAGE_STATUS" };
export type CaptureMode = "full-page" | "visible" | "region";
export type StartCaptureMessage = {
  type: "START_CAPTURE";
  mode: CaptureMode;
  captureSessionId?: string;
};
export type StartHotspotCaptureMessage = {
  type: "START_HOTSPOT_CAPTURE";
  targetPlatform: "douyin" | "xiaohongshu";
};
export type SetHotspotContextMessage = {
  type: "SET_HOTSPOT_CONTEXT";
  targetPlatform: "douyin" | "xiaohongshu";
};
export type CaptureContext = {
  platform: "douyin" | "xiaohongshu";
  pageVersion: string;
  pageSignature: string;
};
export type StartSafeCaptureMessage =
  | { type: "START_SAFE_CAPTURE" }
  | ({ type: "START_SAFE_CAPTURE"; tabId: number; armGeneration: number } & CaptureContext);
export type CaptureVisibleTabMessage = {
  type: "CAPTURE_VISIBLE_TAB";
  pageSignature: string;
};
export type FullPageCaptureMetadata = CaptureContext & {
  captureSessionId: string;
  url: string;
  viewport: { width: number; height: number; devicePixelRatio: number };
  scrollY: number;
};
export type ArmFullPageCaptureMessage = {
  type: "ARM_FULL_PAGE_CAPTURE";
  tabId: number;
  armGeneration: number;
} & FullPageCaptureMetadata;
export type CaptureFullPageSliceMessage = {
  type: "CAPTURE_FULL_PAGE_SLICE";
  sequence: number;
} & FullPageCaptureMetadata;
export type EndFullPageCaptureMessage = {
  type: "END_FULL_PAGE_CAPTURE";
  captureSessionId: string;
};
export type GetCaptureBindingMessage = { type: "GET_CAPTURE_BINDING"; captureSessionId?: string } & CaptureContext;
export type ClearCaptureBindingMessage = { type: "CLEAR_CAPTURE_BINDING" } & CaptureContext;
export type OpenReviewMessage = { type: "OPEN_REVIEW"; url: string };
export type GetSessionBindingMessage = { type: "GET_SESSION_BINDING" };
export type UnlinkSessionMessage = { type: "UNLINK_SESSION" };
export type CaptureCompletionMetadata = {
  capture_mode: CaptureMode;
  complete: boolean;
  stop_reason: string;
  slice_count: number;
};
export type UploadCaptureTaskMessage = {
  type: "UPLOAD_CAPTURE_TASK";
  screenshotDataUrl: string;
  idempotencyKey: string;
  collectedAt: string;
  captureMetadata: CaptureCompletionMetadata;
} & CaptureContext;
export type PollCaptureTaskMessage = {
  type: "POLL_CAPTURE_TASK";
  taskId: string;
} & CaptureContext;
export type UploadHotspotCaptureMessage = {
  type: "UPLOAD_HOTSPOT_CAPTURE";
  screenshotDataUrl: string;
  idempotencyKey: string;
  collectedAt: string;
  sourceUrl: string;
  pageTitle: string;
  captureMetadata: CaptureCompletionMetadata;
} & CaptureContext;
export type PollHotspotCaptureMessage = {
  type: "POLL_HOTSPOT_CAPTURE";
  captureId: string;
} & CaptureContext;

export type RuntimeMessage =
  | GetPageStatusMessage
  | StartCaptureMessage
  | StartHotspotCaptureMessage
  | SetHotspotContextMessage
  | StartSafeCaptureMessage
  | GetCaptureBindingMessage
  | ClearCaptureBindingMessage
  | CaptureVisibleTabMessage
  | ArmFullPageCaptureMessage
  | CaptureFullPageSliceMessage
  | EndFullPageCaptureMessage
  | OpenReviewMessage
  | GetSessionBindingMessage
  | UnlinkSessionMessage
  | UploadCaptureTaskMessage
  | PollCaptureTaskMessage
  | UploadHotspotCaptureMessage
  | PollHotspotCaptureMessage;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const hasExactKeys = (value: Record<string, unknown>, keys: string[]) => {
  const actual = Object.keys(value).sort();
  return actual.length === keys.length && actual.every((key, index) => key === [...keys].sort()[index]);
};

const validViewport = (value: unknown): value is FullPageCaptureMetadata["viewport"] =>
  isRecord(value) &&
  hasExactKeys(value, ["width", "height", "devicePixelRatio"]) &&
  Number.isInteger(value.width) && Number(value.width) > 0 && Number(value.width) <= 32_000 &&
  Number.isInteger(value.height) && Number(value.height) > 0 && Number(value.height) <= 32_000 &&
  typeof value.devicePixelRatio === "number" && Number.isFinite(value.devicePixelRatio) &&
  value.devicePixelRatio >= 0.5 && value.devicePixelRatio <= 8;

const validFullPageMetadata = (value: Record<string, unknown>): value is Record<string, unknown> & FullPageCaptureMetadata =>
  (value.platform === "douyin" || value.platform === "xiaohongshu") &&
  typeof value.pageVersion === "string" && value.pageVersion.length > 0 && value.pageVersion.length <= 80 &&
  typeof value.pageSignature === "string" && value.pageSignature.length > 0 && value.pageSignature.length <= 160 &&
  typeof value.captureSessionId === "string" && /^[A-Za-z0-9_-]{1,128}$/.test(value.captureSessionId) &&
  typeof value.url === "string" && value.url.length > 0 && value.url.length <= 2048 &&
  validViewport(value.viewport) &&
  typeof value.scrollY === "number" && Number.isFinite(value.scrollY) && value.scrollY >= 0;

const validCaptureContext = (value: Record<string, unknown>): value is Record<string, unknown> & CaptureContext =>
  (value.platform === "douyin" || value.platform === "xiaohongshu") &&
  typeof value.pageVersion === "string" && value.pageVersion.length > 0 && value.pageVersion.length <= 80 &&
  typeof value.pageSignature === "string" && value.pageSignature.length > 0 && value.pageSignature.length <= 160;

const validCaptureMetadata = (value: unknown): value is CaptureCompletionMetadata =>
  isRecord(value) &&
  hasExactKeys(value, ["capture_mode", "complete", "stop_reason", "slice_count"]) &&
  (value.capture_mode === "full-page" || value.capture_mode === "visible" || value.capture_mode === "region") &&
  typeof value.complete === "boolean" &&
  typeof value.stop_reason === "string" && value.stop_reason.length > 0 && value.stop_reason.length <= 80 &&
  Number.isSafeInteger(value.slice_count) && Number(value.slice_count) > 0 && Number(value.slice_count) <= 30;

export function parseRuntimeMessage(value: unknown): RuntimeMessage | null {
  if (!isRecord(value) || typeof value.type !== "string") return null;
  if (value.type === "GET_PAGE_STATUS" && hasExactKeys(value, ["type"])) {
    return { type: "GET_PAGE_STATUS" };
  }
  if (
    value.type === "START_CAPTURE" &&
    ((hasExactKeys(value, ["type", "mode"]) && (value.mode === "full-page" || value.mode === "visible" || value.mode === "region")) ||
      (hasExactKeys(value, ["type", "mode", "captureSessionId"]) &&
        (value.mode === "full-page" || value.mode === "visible" || value.mode === "region") &&
        typeof value.captureSessionId === "string" && /^[A-Za-z0-9_-]{1,128}$/.test(value.captureSessionId)))
  ) {
    return {
      type: "START_CAPTURE",
      mode: value.mode,
      ...(typeof value.captureSessionId === "string" ? { captureSessionId: value.captureSessionId } : {}),
    };
  }
  if (
    value.type === "START_HOTSPOT_CAPTURE" &&
    hasExactKeys(value, ["type", "targetPlatform"]) &&
    (value.targetPlatform === "douyin" || value.targetPlatform === "xiaohongshu")
  ) {
    return { type: "START_HOTSPOT_CAPTURE", targetPlatform: value.targetPlatform };
  }
  if (
    value.type === "SET_HOTSPOT_CONTEXT" &&
    hasExactKeys(value, ["type", "targetPlatform"]) &&
    (value.targetPlatform === "douyin" || value.targetPlatform === "xiaohongshu")
  ) {
    return { type: "SET_HOTSPOT_CONTEXT", targetPlatform: value.targetPlatform };
  }
  if (value.type === "GET_SESSION_BINDING" && hasExactKeys(value, ["type"])) return { type: "GET_SESSION_BINDING" };
  if (value.type === "UNLINK_SESSION" && hasExactKeys(value, ["type"])) return { type: "UNLINK_SESSION" };
  if (
    value.type === "UPLOAD_CAPTURE_TASK" &&
    hasExactKeys(value, ["type", "platform", "pageVersion", "pageSignature", "screenshotDataUrl", "idempotencyKey", "collectedAt", "captureMetadata"]) &&
    validCaptureContext(value) &&
    typeof value.screenshotDataUrl === "string" &&
    value.screenshotDataUrl.startsWith("data:image/png;base64,") &&
    value.screenshotDataUrl.length <= 14_000_000 &&
    typeof value.idempotencyKey === "string" && /^[A-Za-z0-9._:-]{1,160}$/.test(value.idempotencyKey) &&
    typeof value.collectedAt === "string" && value.collectedAt.length <= 64 && Number.isFinite(Date.parse(value.collectedAt)) &&
    validCaptureMetadata(value.captureMetadata)
  ) {
    return {
      type: "UPLOAD_CAPTURE_TASK",
      platform: value.platform,
      pageVersion: value.pageVersion,
      pageSignature: value.pageSignature,
      screenshotDataUrl: value.screenshotDataUrl,
      idempotencyKey: value.idempotencyKey,
      collectedAt: value.collectedAt,
      captureMetadata: value.captureMetadata,
    };
  }
  if (
    value.type === "POLL_CAPTURE_TASK" &&
    hasExactKeys(value, ["type", "platform", "pageVersion", "pageSignature", "taskId"]) &&
    validCaptureContext(value) &&
    typeof value.taskId === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value.taskId)
  ) {
    return {
      type: "POLL_CAPTURE_TASK",
      platform: value.platform,
      pageVersion: value.pageVersion,
      pageSignature: value.pageSignature,
      taskId: value.taskId,
    };
  }
  if (
    value.type === "UPLOAD_HOTSPOT_CAPTURE" &&
    hasExactKeys(value, ["type", "platform", "pageVersion", "pageSignature", "screenshotDataUrl", "idempotencyKey", "collectedAt", "sourceUrl", "pageTitle", "captureMetadata"]) &&
    validCaptureContext(value) &&
    value.pageVersion === "hotspot-public-page-v1" &&
    typeof value.screenshotDataUrl === "string" &&
    value.screenshotDataUrl.startsWith("data:image/png;base64,") &&
    value.screenshotDataUrl.length <= 14_000_000 &&
    typeof value.idempotencyKey === "string" && /^[A-Za-z0-9._:-]{1,160}$/.test(value.idempotencyKey) &&
    typeof value.collectedAt === "string" && value.collectedAt.length <= 64 && Number.isFinite(Date.parse(value.collectedAt)) &&
    typeof value.sourceUrl === "string" && value.sourceUrl.startsWith("https://") && value.sourceUrl.length <= 2_000 &&
    typeof value.pageTitle === "string" && value.pageTitle.trim().length > 0 && value.pageTitle.length <= 300 &&
    validCaptureMetadata(value.captureMetadata)
  ) {
    return {
      type: "UPLOAD_HOTSPOT_CAPTURE",
      platform: value.platform,
      pageVersion: value.pageVersion,
      pageSignature: value.pageSignature,
      screenshotDataUrl: value.screenshotDataUrl,
      idempotencyKey: value.idempotencyKey,
      collectedAt: value.collectedAt,
      sourceUrl: value.sourceUrl,
      pageTitle: value.pageTitle,
      captureMetadata: value.captureMetadata,
    };
  }
  if (
    value.type === "POLL_HOTSPOT_CAPTURE" &&
    hasExactKeys(value, ["type", "platform", "pageVersion", "pageSignature", "captureId"]) &&
    validCaptureContext(value) &&
    value.pageVersion === "hotspot-public-page-v1" &&
    typeof value.captureId === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value.captureId)
  ) {
    return {
      type: "POLL_HOTSPOT_CAPTURE",
      platform: value.platform,
      pageVersion: value.pageVersion,
      pageSignature: value.pageSignature,
      captureId: value.captureId,
    };
  }
  if (value.type === "END_FULL_PAGE_CAPTURE" && hasExactKeys(value, ["type", "captureSessionId"]) && typeof value.captureSessionId === "string" && /^[A-Za-z0-9_-]{1,128}$/.test(value.captureSessionId)) {
    return { type: "END_FULL_PAGE_CAPTURE", captureSessionId: value.captureSessionId };
  }
  if (
    value.type === "ARM_FULL_PAGE_CAPTURE" &&
    hasExactKeys(value, ["type", "tabId", "armGeneration", "captureSessionId", "platform", "pageVersion", "pageSignature", "url", "viewport", "scrollY"]) &&
    Number.isSafeInteger(value.tabId) && Number(value.tabId) >= 0 &&
    Number.isSafeInteger(value.armGeneration) && Number(value.armGeneration) > 0 &&
    validFullPageMetadata(value)
  ) {
    return {
      type: "ARM_FULL_PAGE_CAPTURE", tabId: Number(value.tabId), armGeneration: Number(value.armGeneration), captureSessionId: value.captureSessionId,
      platform: value.platform, pageVersion: value.pageVersion, pageSignature: value.pageSignature,
      url: value.url, viewport: value.viewport, scrollY: value.scrollY,
    };
  }
  if (
    value.type === "CAPTURE_FULL_PAGE_SLICE" &&
    hasExactKeys(value, ["type", "captureSessionId", "sequence", "platform", "pageVersion", "pageSignature", "url", "viewport", "scrollY"]) &&
    Number.isSafeInteger(value.sequence) && Number(value.sequence) >= 0 && Number(value.sequence) < 30 && validFullPageMetadata(value)
  ) {
    return {
      type: "CAPTURE_FULL_PAGE_SLICE", sequence: Number(value.sequence), captureSessionId: value.captureSessionId,
      platform: value.platform, pageVersion: value.pageVersion, pageSignature: value.pageSignature,
      url: value.url, viewport: value.viewport, scrollY: value.scrollY,
    };
  }
  if (value.type === "START_SAFE_CAPTURE") {
    if (hasExactKeys(value, ["type"])) return { type: "START_SAFE_CAPTURE" };
    if (
      hasExactKeys(value, ["type", "tabId", "armGeneration", "platform", "pageVersion", "pageSignature"]) &&
      Number.isSafeInteger(value.tabId) &&
      Number(value.tabId) >= 0 &&
      Number.isSafeInteger(value.armGeneration) &&
      Number(value.armGeneration) > 0 &&
      (value.platform === "douyin" || value.platform === "xiaohongshu") &&
      typeof value.pageVersion === "string" &&
      value.pageVersion.length > 0 &&
      value.pageVersion.length <= 80 &&
      typeof value.pageSignature === "string" &&
      value.pageSignature.length > 0 &&
      value.pageSignature.length <= 160
    ) {
      return {
        type: "START_SAFE_CAPTURE",
        tabId: Number(value.tabId),
        armGeneration: Number(value.armGeneration),
        platform: value.platform,
        pageVersion: value.pageVersion,
        pageSignature: value.pageSignature,
      };
    }
    return null;
  }
  if (
    (value.type === "GET_CAPTURE_BINDING" || value.type === "CLEAR_CAPTURE_BINDING") &&
    (
      hasExactKeys(value, ["type", "platform", "pageVersion", "pageSignature"]) ||
      (value.type === "GET_CAPTURE_BINDING" &&
        hasExactKeys(value, ["type", "platform", "pageVersion", "pageSignature", "captureSessionId"]) &&
        typeof value.captureSessionId === "string" && /^[A-Za-z0-9_-]{1,128}$/.test(value.captureSessionId))
    ) &&
    (value.platform === "douyin" || value.platform === "xiaohongshu") &&
    typeof value.pageVersion === "string" &&
    value.pageVersion.length > 0 &&
    value.pageVersion.length <= 80 &&
    typeof value.pageSignature === "string" &&
    value.pageSignature.length > 0 &&
    value.pageSignature.length <= 160
  ) {
    return {
      type: value.type,
      platform: value.platform,
      pageVersion: value.pageVersion,
      pageSignature: value.pageSignature,
      ...(typeof value.captureSessionId === "string" ? { captureSessionId: value.captureSessionId } : {}),
    };
  }
  if (
    value.type === "CAPTURE_VISIBLE_TAB" &&
    hasExactKeys(value, ["type", "pageSignature"]) &&
    typeof value.pageSignature === "string" &&
    value.pageSignature.length > 0 &&
    value.pageSignature.length <= 160
  ) {
    return { type: "CAPTURE_VISIBLE_TAB", pageSignature: value.pageSignature };
  }
  if (
    value.type === "OPEN_REVIEW" &&
    hasExactKeys(value, ["type", "url"]) &&
    typeof value.url === "string" &&
    value.url.length > 0 &&
    value.url.length <= 2048
  ) {
    return { type: "OPEN_REVIEW", url: value.url };
  }
  return null;
}
