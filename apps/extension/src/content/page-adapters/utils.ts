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

export const unsupported = (platform: Platform, reason: string): PageDetection => ({
  supported: false,
  platform,
  pageVersion: "unknown",
  signature: `${platform}:unsupported`,
  captureRegion: null,
  sensitiveRegions: [],
  reason,
});
