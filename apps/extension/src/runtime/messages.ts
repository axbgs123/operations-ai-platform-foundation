export type GetPageStatusMessage = { type: "GET_PAGE_STATUS" };
export type CaptureContext = {
  platform: "douyin" | "xiaohongshu";
  pageVersion: string;
  pageSignature: string;
};
export type StartSafeCaptureMessage =
  | { type: "START_SAFE_CAPTURE" }
  | ({ type: "START_SAFE_CAPTURE"; tabId: number } & CaptureContext);
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
} & FullPageCaptureMetadata;
export type CaptureFullPageSliceMessage = {
  type: "CAPTURE_FULL_PAGE_SLICE";
  sequence: number;
} & FullPageCaptureMetadata;
export type EndFullPageCaptureMessage = {
  type: "END_FULL_PAGE_CAPTURE";
  captureSessionId: string;
};
export type GetCaptureBindingMessage = { type: "GET_CAPTURE_BINDING" } & CaptureContext;
export type ClearCaptureBindingMessage = { type: "CLEAR_CAPTURE_BINDING" } & CaptureContext;
export type OpenReviewMessage = { type: "OPEN_REVIEW"; url: string };
export type GetSessionBindingMessage = { type: "GET_SESSION_BINDING" };
export type UnlinkSessionMessage = { type: "UNLINK_SESSION" };

export type RuntimeMessage =
  | GetPageStatusMessage
  | StartSafeCaptureMessage
  | GetCaptureBindingMessage
  | ClearCaptureBindingMessage
  | CaptureVisibleTabMessage
  | ArmFullPageCaptureMessage
  | CaptureFullPageSliceMessage
  | EndFullPageCaptureMessage
  | OpenReviewMessage
  | GetSessionBindingMessage
  | UnlinkSessionMessage;

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

export function parseRuntimeMessage(value: unknown): RuntimeMessage | null {
  if (!isRecord(value) || typeof value.type !== "string") return null;
  if (value.type === "GET_PAGE_STATUS" && hasExactKeys(value, ["type"])) {
    return { type: "GET_PAGE_STATUS" };
  }
  if (value.type === "GET_SESSION_BINDING" && hasExactKeys(value, ["type"])) return { type: "GET_SESSION_BINDING" };
  if (value.type === "UNLINK_SESSION" && hasExactKeys(value, ["type"])) return { type: "UNLINK_SESSION" };
  if (value.type === "END_FULL_PAGE_CAPTURE" && hasExactKeys(value, ["type", "captureSessionId"]) && typeof value.captureSessionId === "string" && /^[A-Za-z0-9_-]{1,128}$/.test(value.captureSessionId)) {
    return { type: "END_FULL_PAGE_CAPTURE", captureSessionId: value.captureSessionId };
  }
  if (
    value.type === "ARM_FULL_PAGE_CAPTURE" &&
    hasExactKeys(value, ["type", "tabId", "captureSessionId", "platform", "pageVersion", "pageSignature", "url", "viewport", "scrollY"]) &&
    Number.isSafeInteger(value.tabId) && Number(value.tabId) >= 0 && validFullPageMetadata(value)
  ) {
    return {
      type: "ARM_FULL_PAGE_CAPTURE", tabId: Number(value.tabId), captureSessionId: value.captureSessionId,
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
      hasExactKeys(value, ["type", "tabId", "platform", "pageVersion", "pageSignature"]) &&
      Number.isSafeInteger(value.tabId) &&
      Number(value.tabId) >= 0 &&
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
        platform: value.platform,
        pageVersion: value.pageVersion,
        pageSignature: value.pageSignature,
      };
    }
    return null;
  }
  if (
    (value.type === "GET_CAPTURE_BINDING" || value.type === "CLEAR_CAPTURE_BINDING") &&
    hasExactKeys(value, ["type", "platform", "pageVersion", "pageSignature"]) &&
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
