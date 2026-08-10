import { normalizeServerOrigin } from "./server";

export type ExtensionBinding = {
  serverOrigin: string;
  webOrigin: string;
  workspaceId: string;
  workspaceName: string;
  memberDisplayName: string;
  accessToken: string;
  expiresAt: string;
  providerMode: "mock" | "qianwen" | "unavailable";
  region: string | null;
};

export type BindingStore = {
  load(): Promise<ExtensionBinding | null>;
  save(binding: ExtensionBinding): Promise<void>;
  clear(): Promise<void>;
};

export function createMemoryBindingStore(): BindingStore {
  let binding: ExtensionBinding | null = null;
  return {
    async load() {
      return binding;
    },
    async save(next) {
      binding = { ...next };
    },
    async clear() {
      binding = null;
    },
  };
}

type SessionStorageArea = {
  get(key: string): Promise<Record<string, unknown>>;
  set(values: Record<string, unknown>): Promise<void>;
  remove(key: string): Promise<void>;
};

const storageKey = "extensionBinding";
const bindingFields = [
  "serverOrigin",
  "webOrigin",
  "workspaceId",
  "workspaceName",
  "memberDisplayName",
  "accessToken",
  "expiresAt",
  "providerMode",
  "region",
] as const;
const workspaceIdPattern =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

function normalizeWebOrigin(value: unknown): string | null {
  if (typeof value !== "string") return null;
  try {
    return normalizeServerOrigin(value);
  } catch {
    return null;
  }
}

export function parseExtensionBinding(value: unknown): ExtensionBinding | null {
  if (!isRecord(value) || Object.keys(value).length !== bindingFields.length) {
    return null;
  }
  if (!bindingFields.every((field) => Object.hasOwn(value, field))) return null;
  const {
    serverOrigin,
    webOrigin,
    workspaceId,
    workspaceName,
    memberDisplayName,
    accessToken,
    expiresAt,
    providerMode,
    region,
  } = value;
  if (
    typeof serverOrigin !== "string" ||
    typeof workspaceId !== "string" ||
    !workspaceIdPattern.test(workspaceId) ||
    typeof workspaceName !== "string" ||
    workspaceName.trim() === "" ||
    typeof memberDisplayName !== "string" ||
    memberDisplayName.trim() === "" ||
    typeof accessToken !== "string" ||
    accessToken === "" ||
    typeof expiresAt !== "string" ||
    !Number.isFinite(Date.parse(expiresAt)) ||
    (providerMode !== "mock" &&
      providerMode !== "qianwen" &&
      providerMode !== "unavailable") ||
    (region !== null && typeof region !== "string")
  ) {
    return null;
  }
  let normalizedServerOrigin: string;
  try {
    normalizedServerOrigin = normalizeServerOrigin(String(serverOrigin));
  } catch {
    return null;
  }
  const normalizedWebOrigin = normalizeWebOrigin(webOrigin);
  if (!normalizedWebOrigin) return null;
  return {
    serverOrigin: normalizedServerOrigin,
    webOrigin: normalizedWebOrigin,
    workspaceId,
    workspaceName,
    memberDisplayName,
    accessToken,
    expiresAt,
    providerMode,
    region,
  };
}

export function createSessionBindingStore(
  session: SessionStorageArea,
): BindingStore {
  return {
    async load() {
      const result = await session.get(storageKey);
      const stored = result[storageKey];
      if (stored === undefined) return null;
      const binding = parseExtensionBinding(stored);
      if (binding) return binding;
      await session.remove(storageKey);
      return null;
    },
    async save(binding) {
      const parsed = parseExtensionBinding(binding);
      if (!parsed) throw new Error("invalid extension binding");
      await session.set({ [storageKey]: parsed });
    },
    async clear() {
      await session.remove(storageKey);
    },
  };
}
