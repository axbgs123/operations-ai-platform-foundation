import type { components } from "@operations-ai/shared-schemas";

import { normalizeServerOrigin } from "./server";
import { parseExtensionBinding, type BindingStore, type ExtensionBinding } from "./storage";

type PairResponse = components["schemas"]["ExtensionBindResponse"];

export type PairingInput = {
  serverOrigin: string;
  pairingCode: string;
  clientId: string;
};

export type PairingDependencies = {
  fetcher: typeof fetch;
  store: BindingStore;
  clearPairingCode(): void;
  requestOriginPermission?(originPattern: string): Promise<boolean>;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

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

export async function pairExtension(
  input: PairingInput,
  dependencies: PairingDependencies,
): Promise<PairResponse> {
  try {
    const serverOrigin = normalizeServerOrigin(input.serverOrigin);
    if (
      dependencies.requestOriginPermission &&
      !(await dependencies.requestOriginPermission(`${serverOrigin}/*`))
    ) {
      throw new Error("服务器权限未授权");
    }
    const response = await dependencies.fetcher(
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
        }),
      },
    );
    if (!response.ok) throw new Error("服务器配对失败");
    const payload: unknown = await response.json();
    const binding = bindingFromPairResponse(payload, serverOrigin);
    if (!binding) throw new Error("服务器配对失败");
    await dependencies.store.save(binding);
    return payload as PairResponse;
  } catch {
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
