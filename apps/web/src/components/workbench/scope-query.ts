import type { components } from "@operations-ai/shared-schemas";


export type WorkbenchAccount =
  components["schemas"]["WorkbenchAccountOption"];
export type WorkbenchPlatform = WorkbenchAccount["platform"];

export type WorkbenchScope = {
  platform?: WorkbenchPlatform;
  accountId?: string;
};

type SearchParamReader = {
  get(name: string): string | null;
};

export type SidebarPreference = "expanded" | "collapsed";

const PLATFORM_VALUES = new Set<WorkbenchPlatform>([
  "douyin",
  "xiaohongshu",
]);

const SAFE_WORKSPACE_ROUTES = [
  /^\/accounts(?:\/[A-Za-z0-9-]+(?:\/settings)?)?$/,
  /^\/columns$/,
  /^\/contents(?:\/(?:new|[A-Za-z0-9-]+(?:\/analysis)?))?$/,
  /^\/imports$/,
  /^\/analysis$/,
  /^\/viral-library$/,
  /^\/styles(?:\/[A-Za-z0-9-]+)?$/,
  /^\/facts$/,
  /^\/generation$/,
  /^\/preflight$/,
  /^\/risk-knowledge$/,
  /^\/data-management\/(?:exports|trash)$/,
  /^\/settings(?:\/(?:jobs|members|models))?$/,
] as const;

export function parseWorkbenchScope(
  searchParams: SearchParamReader,
  accounts: readonly WorkbenchAccount[],
): WorkbenchScope {
  const rawPlatform = searchParams.get("platform");
  if (
    rawPlatform !== null
    && !PLATFORM_VALUES.has(rawPlatform as WorkbenchPlatform)
  ) {
    return {};
  }
  const platform = (rawPlatform ?? undefined) as
    | WorkbenchPlatform
    | undefined;
  const rawAccount = searchParams.get("account");
  if (!rawAccount) return platform ? { platform } : {};

  const account = accounts.find((item) => item.account_id === rawAccount);
  if (!account) return platform ? { platform } : {};
  if (platform && account.platform !== platform) return { platform };
  return {
    platform: platform ?? account.platform,
    accountId: account.account_id,
  };
}

export function toWorkbenchApiScope(scope: WorkbenchScope): {
  platform?: WorkbenchPlatform;
  account_id?: string;
} {
  return {
    ...(scope.platform ? { platform: scope.platform } : {}),
    ...(scope.accountId ? { account_id: scope.accountId } : {}),
  };
}

function decodeReturnValue(value: string): string | undefined {
  let decoded = value;
  for (let pass = 0; pass < 3; pass += 1) {
    try {
      const next = decodeURIComponent(decoded);
      if (next === decoded) return decoded;
      decoded = next;
    } catch {
      return undefined;
    }
  }
  return decoded;
}

export function sanitizeReturnTo(
  workspaceId: string,
  value: string | null | undefined,
): string | undefined {
  if (!value || value.length > 2_000 || value.trim() !== value) {
    return undefined;
  }
  const decoded = decodeReturnValue(value);
  if (
    !decoded
    || decoded.includes("\\")
    || /[\u0000-\u001F\u007F]/.test(decoded)
    || decoded.startsWith("//")
    || /\/(?:\.{1,2})(?:\/|$)/.test(decoded)
  ) {
    return undefined;
  }
  const prefix = `/workspaces/${workspaceId}`;
  if (decoded !== prefix && !decoded.startsWith(`${prefix}/`)) {
    return undefined;
  }
  let parsed: URL;
  try {
    parsed = new URL(decoded, "https://workspace.invalid");
  } catch {
    return undefined;
  }
  if (
    parsed.origin !== "https://workspace.invalid"
    || parsed.hash
    || parsed.searchParams.has("returnTo")
  ) {
    return undefined;
  }
  const suffix = parsed.pathname.slice(prefix.length);
  if (
    suffix !== ""
    && !SAFE_WORKSPACE_ROUTES.some((pattern) => pattern.test(suffix))
  ) {
    return undefined;
  }
  return `${parsed.pathname}${parsed.search}`;
}

export function buildWorkspaceHref(
  workspaceId: string,
  pathname: string,
  scope: WorkbenchScope,
  returnTo?: string,
): string {
  const workspaceRoot = `/workspaces/${workspaceId}`;
  const target = pathname.startsWith(`${workspaceRoot}`)
    ? pathname
    : `${workspaceRoot}${pathname === "/" ? "" : pathname}`;
  const url = new URL(target, "https://workspace.invalid");
  url.search = "";
  if (scope.platform) url.searchParams.set("platform", scope.platform);
  if (scope.accountId) url.searchParams.set("account", scope.accountId);
  const safeReturn = sanitizeReturnTo(workspaceId, returnTo);
  if (safeReturn) url.searchParams.set("returnTo", safeReturn);
  return `${url.pathname}${url.search}`;
}

function sidebarPreferenceKey(memberId: string): string {
  return `operations-ai:sidebar:${memberId}`;
}

export function readSidebarPreference(
  storage: Pick<Storage, "getItem">,
  memberId: string,
): SidebarPreference {
  const stored = storage.getItem(sidebarPreferenceKey(memberId));
  return stored === "collapsed" || stored === "expanded"
    ? stored
    : "expanded";
}

export function writeSidebarPreference(
  storage: Pick<Storage, "setItem">,
  memberId: string,
  preference: SidebarPreference,
): void {
  storage.setItem(sidebarPreferenceKey(memberId), preference);
}
