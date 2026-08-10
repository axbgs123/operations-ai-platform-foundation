import type { components } from "@operations-ai/shared-schemas";

import type { DeviceKeyStore } from "./device-key-store";
import {
  type DeviceRegistration,
  type DeviceRegistrationStore,
} from "./device-registration-store";
import { normalizeServerOrigin } from "./server";
import { parseExtensionBinding, type BindingStore, type ExtensionBinding } from "./storage";

type PairResponse = components["schemas"]["ExtensionPairResponse"];

export type PairingInput = {
  serverOrigin: string;
  pairingCode: string;
  clientId: string;
  deviceLabel?: string;
  extensionVersion?: string;
};

export type PairingDependencies = {
  fetcher: typeof fetch;
  store: BindingStore;
  keyStore?: DeviceKeyStore;
  registrations?: DeviceRegistrationStore;
  clearPairingCode(): void;
  hasOriginPermission?(originPattern: string): Promise<boolean>;
  requestOriginPermission?(originPattern: string): Promise<boolean>;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const hostPermissionPattern = (serverOrigin: string) => {
  const url = new URL(serverOrigin);
  return `${url.protocol}//${url.hostname}/*`;
};

function bindingFromPairResponse(
  payload: unknown,
  serverOrigin: string,
): ExtensionBinding | null {
  if (!isRecord(payload)) return null;
  return parseExtensionBinding({
    serverOrigin,
    webOrigin: payload.web_origin,
    workspaceId: payload.workspace_id,
    workspaceName: payload.workspace_name,
    memberDisplayName: payload.member_display_name,
    accessToken: payload.access_token,
    expiresAt: payload.expires_at,
    providerMode: payload.provider_mode,
    region: payload.region,
  });
}

function registrationFromPairResponse(
  payload: unknown,
  serverOrigin: string,
  deviceId: string,
  deviceLabel: string,
  extensionVersion: string,
): DeviceRegistration | null {
  if (!isRecord(payload) || payload.device_id !== deviceId) return null;
  const binding = bindingFromPairResponse(payload, serverOrigin);
  if (!binding) return null;
  return {
    serverOrigin: binding.serverOrigin,
    webOrigin: binding.webOrigin,
    workspaceId: binding.workspaceId,
    workspaceName: binding.workspaceName,
    memberDisplayName: binding.memberDisplayName,
    providerMode: binding.providerMode,
    region: binding.region,
    deviceId,
    deviceLabel,
    extensionVersion,
  };
}

export async function pairExtension(
  input: PairingInput,
  dependencies: PairingDependencies,
): Promise<PairResponse> {
  const fetcher = dependencies.fetcher;
  let pairedDevice = false;
  let device: Awaited<ReturnType<DeviceKeyStore["getOrCreate"]>> | null = null;
  try {
    const serverOrigin = normalizeServerOrigin(input.serverOrigin);
    device = dependencies.keyStore ? await dependencies.keyStore.getOrCreate() : null;
    const deviceLabel = input.deviceLabel ?? "Operations AI extension";
    const extensionVersion = input.extensionVersion ?? "0.2.0";
    const permissionPattern = hostPermissionPattern(serverOrigin);
    if (
      dependencies.requestOriginPermission &&
      !(await dependencies.hasOriginPermission?.(permissionPattern)) &&
      !(await dependencies.requestOriginPermission(permissionPattern))
    ) {
      throw new Error("服务器权限未授权");
    }
    const response = await fetcher(
      `${serverOrigin}/v1/extension/pair`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": crypto.randomUUID(),
          "X-Extension-Client": input.clientId,
        },
        body: JSON.stringify({
          pairing_code: input.pairingCode,
          client_id: input.clientId,
          ...(device
            ? {
                device_id: device.deviceId,
                device_public_key_jwk: device.publicJwk,
                device_label: deviceLabel,
                extension_version: extensionVersion,
              }
            : {}),
        }),
      },
    );
    if (!response.ok) throw new Error("服务器配对失败");
    pairedDevice = device !== null;
    const payload: unknown = await response.json();
    const binding = bindingFromPairResponse(payload, serverOrigin);
    if (!binding) throw new Error("服务器配对失败");
    if (device && dependencies.registrations) {
      const registration = registrationFromPairResponse(
        payload,
        serverOrigin,
        device.deviceId,
        deviceLabel,
        extensionVersion,
      );
      if (!registration) throw new Error("服务器配对失败");
      await dependencies.registrations.save(registration);
    }
    await dependencies.store.save(binding);
    return payload as PairResponse;
  } catch {
    if (pairedDevice && device && dependencies.registrations) {
      await Promise.allSettled([
        dependencies.store.clear(),
        dependencies.registrations.clear(),
        dependencies.keyStore?.clear() ?? Promise.resolve(),
      ]);
    }
    throw new Error("服务器配对失败");
  } finally {
    dependencies.clearPairingCode();
  }
}

export function bindingDisclosure(
  serverOrigin: string,
  processingMode: string,
): string[] {
  return [
    `截图将上传到：${serverOrigin}`,
    `处理方式：${processingMode}`,
    "识别数据仍需人工确认",
  ];
}

export async function revokeExtension(
  store: BindingStore,
  fetcher: typeof fetch,
): Promise<void> {
  const binding = await store.load();
  try {
    if (binding) {
      const response = await fetcher(`${binding.serverOrigin}/v1/extension/binding`, {
        method: "DELETE",
        headers: {
          Authorization: `Bearer ${binding.accessToken}`,
        },
      });
      if (!response.ok) throw new Error("服务器撤销失败");
    }
  } finally {
    await store.clear();
  }
}
