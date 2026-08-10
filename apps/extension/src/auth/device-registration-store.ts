import { normalizeServerOrigin } from "./server";

export type DeviceRegistration = {
  serverOrigin: string;
  webOrigin: string;
  workspaceId: string;
  workspaceName: string;
  memberDisplayName: string;
  providerMode: "mock" | "qianwen" | "unavailable";
  region: string | null;
  deviceId: string;
  deviceLabel: string;
  extensionVersion: string;
};

export type DeviceRegistrationStore = {
  load(): Promise<DeviceRegistration | null>;
  save(registration: DeviceRegistration): Promise<void>;
  clear(): Promise<void>;
};

export type LocalStorageArea = {
  get(key: string): Promise<Record<string, unknown>>;
  set(values: Record<string, unknown>): Promise<void>;
  remove(key: string): Promise<void>;
};

const storageKey = "extensionDeviceRegistration";
const registrationFields = [
  "serverOrigin", "webOrigin", "workspaceId", "workspaceName", "memberDisplayName",
  "providerMode", "region", "deviceId", "deviceLabel", "extensionVersion",
] as const;
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

function origin(value: unknown): string | null {
  if (typeof value !== "string") return null;
  try { return normalizeServerOrigin(value); } catch { return null; }
}

export function parseDeviceRegistration(value: unknown): DeviceRegistration | null {
  if (!isRecord(value) || Object.keys(value).length !== registrationFields.length) return null;
  if (!registrationFields.every((field) => Object.hasOwn(value, field))) return null;
  const serverOrigin = origin(value.serverOrigin);
  const webOrigin = origin(value.webOrigin);
  if (!serverOrigin || !webOrigin ||
    typeof value.workspaceId !== "string" || !uuidPattern.test(value.workspaceId) ||
    typeof value.workspaceName !== "string" || value.workspaceName.trim() === "" ||
    typeof value.memberDisplayName !== "string" || value.memberDisplayName.trim() === "" ||
    (value.providerMode !== "mock" && value.providerMode !== "qianwen" && value.providerMode !== "unavailable") ||
    (value.region !== null && typeof value.region !== "string") ||
    typeof value.deviceId !== "string" || !uuidPattern.test(value.deviceId) ||
    typeof value.deviceLabel !== "string" || value.deviceLabel.trim() === "" ||
    typeof value.extensionVersion !== "string" || value.extensionVersion.trim() === ""
  ) return null;
  return {
    serverOrigin, webOrigin, workspaceId: value.workspaceId, workspaceName: value.workspaceName,
    memberDisplayName: value.memberDisplayName, providerMode: value.providerMode, region: value.region,
    deviceId: value.deviceId, deviceLabel: value.deviceLabel, extensionVersion: value.extensionVersion,
  };
}

export function createMemoryDeviceRegistrationStore(): DeviceRegistrationStore {
  let registration: DeviceRegistration | null = null;
  return {
    async load() { return registration ? { ...registration } : null; },
    async save(value) {
      const parsed = parseDeviceRegistration(value);
      if (!parsed) throw new Error("invalid device registration");
      registration = parsed;
    },
    async clear() { registration = null; },
  };
}

export function createLocalDeviceRegistrationStore(local: LocalStorageArea): DeviceRegistrationStore {
  return {
    async load() {
      const stored = (await local.get(storageKey))[storageKey];
      if (stored === undefined) return null;
      const registration = parseDeviceRegistration(stored);
      if (registration) return registration;
      await local.remove(storageKey);
      return null;
    },
    async save(value) {
      const registration = parseDeviceRegistration(value);
      if (!registration) throw new Error("invalid device registration");
      await local.set({ [storageKey]: registration });
    },
    clear: () => local.remove(storageKey),
  };
}
