import type { PageDetection, Platform } from "./base";

export const parseRect = (value: string | undefined) => {
  if (!value) return null;
  const numbers = value.split(",").map((part) => Number(part.trim()));
  if (numbers.length !== 4 || numbers.some((part) => !Number.isFinite(part) || part < 0)) return null;
  const [x, y, width, height] = numbers;
  if (width === 0 || height === 0) return null;
  return { x, y, width, height };
};

export const stableFingerprint = (parts: string[]): string => {
  let hash = 2166136261;
  for (const char of parts.join("|")) {
    hash ^= char.charCodeAt(0);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16).padStart(16, "0");
};

const normalizedText = (value: string | null | undefined) =>
  (value ?? "").replace(/\s+/g, " ").trim().slice(0, 512);

const elementFingerprint = (element: Element) => stableFingerprint([
  element.tagName,
  element.getAttribute("data-content-id") ?? "",
  element.getAttribute("data-row-key") ?? "",
  element.getAttribute("data-account-id") ?? "",
  element.getAttribute("data-filter") ?? "",
  element.getAttribute("data-filter-value") ?? "",
  element.getAttribute("aria-selected") ?? "",
  element.tagName === "INPUT" || element.tagName === "SELECT"
    ? (element as HTMLInputElement | HTMLSelectElement).value
    : "",
  normalizedText(element.textContent),
]);

export function createPageSignatureTracker(platform: Platform, version: string) {
  const states = new WeakMap<Document, { rows: string[]; generation: number }>();
  return (url: URL, document: Document): string => {
    const rows = Array.from(document.querySelectorAll(
      "[data-content-id], [data-row-key], tbody tr, [role='row'], article",
    )).map(elementFingerprint);
    const previous = states.get(document);
    let generation = previous?.generation ?? 0;
    if (previous) {
      const priorRowsChanged = previous.rows.length > rows.length ||
        previous.rows.some((row, index) => rows[index] !== row);
      if (priorRowsChanged) generation += 1;
    }
    states.set(document, { rows, generation });

    const query = [...url.searchParams.entries()]
      .sort(([leftKey, leftValue], [rightKey, rightValue]) =>
        leftKey.localeCompare(rightKey) || leftValue.localeCompare(rightValue))
      .map(([key, value]) => `${key}=${value}`);
    const anchors = Array.from(document.querySelectorAll(
      "[data-account-id], [data-filter], [data-filter-value], [aria-selected='true'], select",
    )).map(elementFingerprint);
    return `${platform}:${stableFingerprint([
      version,
      url.hostname,
      url.pathname,
      url.hash,
      ...query,
      ...anchors,
      `content-generation:${generation}`,
    ])}`;
  };
}

export const unsupported = (platform: Platform, reason: string): PageDetection => ({
  supported: false,
  platform,
  pageVersion: "unknown",
  signature: `${platform}:unsupported`,
  captureRegion: null,
  sensitiveRegions: [],
  reason,
});
