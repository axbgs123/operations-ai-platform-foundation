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
export type OpenReviewMessage = { type: "OPEN_REVIEW"; url: string };

export type RuntimeMessage =
  | GetPageStatusMessage
  | StartSafeCaptureMessage
  | CaptureVisibleTabMessage
  | OpenReviewMessage;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const hasExactKeys = (value: Record<string, unknown>, keys: string[]) => {
  const actual = Object.keys(value).sort();
  return actual.length === keys.length && actual.every((key, index) => key === [...keys].sort()[index]);
};

export function parseRuntimeMessage(value: unknown): RuntimeMessage | null {
  if (!isRecord(value) || typeof value.type !== "string") return null;
  if (value.type === "GET_PAGE_STATUS" && hasExactKeys(value, ["type"])) {
    return { type: "GET_PAGE_STATUS" };
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
