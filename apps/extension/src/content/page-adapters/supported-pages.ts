export type VerificationStatus =
  | "fixture_verified"
  | "real_page_verified"
  | "partially_verified"
  | "unverified"
  | "unsupported"
  | "stale";

export type SupportedPage = {
  platform: "douyin" | "xiaohongshu";
  urlPattern: string;
  pageName: string;
  pageVersion: string;
  pageSignature: string;
  signaturePrefix: string;
  requiredAnchors: string[];
  captureRegion: { x: number; y: number; width: number; height: number };
  sensitiveRegions: string[];
  recognizableFields: string[];
  knownMissingFields: string[];
  fixtureVerifiedAt: string;
  realPageVerifiedAt: string | null;
  verifiedBrowsers: string[];
  verifiedOperatingSystems: string[];
  fixtureEnvironment: string;
  verificationStatus: VerificationStatus;
  staleAfterDays: number;
  degradation: string;
};

const statuses = new Set<VerificationStatus>([
  "fixture_verified",
  "real_page_verified",
  "partially_verified",
  "unverified",
  "unsupported",
  "stale",
]);

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null;

function isSupportedPage(value: unknown): value is SupportedPage {
  if (!isRecord(value) || !isRecord(value.captureRegion)) return false;
  const status = value.verificationStatus;
  const realVerified = status === "real_page_verified";
  return (
    (value.platform === "douyin" || value.platform === "xiaohongshu") &&
    typeof value.urlPattern === "string" &&
    value.urlPattern.startsWith("https://") &&
    !value.urlPattern.includes("<all_urls>") &&
    typeof value.pageName === "string" &&
    typeof value.pageVersion === "string" &&
    typeof value.pageSignature === "string" &&
    value.pageSignature.startsWith(`${value.platform}:`) &&
    typeof value.signaturePrefix === "string" &&
    Array.isArray(value.requiredAnchors) &&
    Array.isArray(value.sensitiveRegions) &&
    Array.isArray(value.recognizableFields) &&
    Array.isArray(value.knownMissingFields) &&
    typeof value.fixtureVerifiedAt === "string" &&
    (typeof value.realPageVerifiedAt === "string" ||
      value.realPageVerifiedAt === null) &&
    Array.isArray(value.verifiedBrowsers) &&
    Array.isArray(value.verifiedOperatingSystems) &&
    typeof value.fixtureEnvironment === "string" &&
    typeof status === "string" &&
    statuses.has(status as VerificationStatus) &&
    typeof value.staleAfterDays === "number" &&
    typeof value.degradation === "string" &&
    (!realVerified ||
      (value.realPageVerifiedAt !== null &&
        value.verifiedBrowsers.length > 0 &&
        value.verifiedOperatingSystems.length > 0)) &&
    (realVerified ||
      (value.realPageVerifiedAt === null &&
        value.verifiedBrowsers.length === 0 &&
        value.verifiedOperatingSystems.length === 0))
  );
}

export function parseSupportedPages(value: unknown): SupportedPage[] {
  if (!Array.isArray(value) || !value.every(isSupportedPage)) {
    throw new Error("invalid supported page registry");
  }
  const platforms = value.map((page) => page.platform);
  if (
    platforms.length !== 2 ||
    new Set(platforms).size !== platforms.length ||
    !platforms.includes("douyin") ||
    !platforms.includes("xiaohongshu")
  ) {
    throw new Error("invalid supported page registry");
  }
  return value;
}

export function effectiveVerificationStatus(
  page: SupportedPage,
  now = new Date(),
): VerificationStatus {
  const verifiedAt = new Date(
    `${page.realPageVerifiedAt ?? page.fixtureVerifiedAt}T00:00:00Z`,
  );
  const ageDays = (now.getTime() - verifiedAt.getTime()) / 86_400_000;
  return ageDays > page.staleAfterDays ? "stale" : page.verificationStatus;
}
