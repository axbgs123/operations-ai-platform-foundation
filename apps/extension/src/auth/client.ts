import type { components } from "@operations-ai/shared-schemas";

import { normalizeServerOrigin } from "./server";
import type { BindingStore } from "./storage";

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

export async function pairExtension(
  input: PairingInput,
  dependencies: PairingDependencies,
): Promise<PairResponse> {
  const serverOrigin = normalizeServerOrigin(input.serverOrigin);
  try {
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
    const payload = (await response.json()) as PairResponse;
    const providerMode =
      payload.provider_mode === "mock" ||
      payload.provider_mode === "qianwen" ||
      payload.provider_mode === "unavailable"
        ? payload.provider_mode
        : "unavailable";
    await dependencies.store.save({
      serverOrigin,
      webOrigin: payload.web_origin,
      workspaceId: payload.workspace_id,
      workspaceName: payload.workspace_name,
      memberDisplayName: payload.member_display_name,
      accessToken: payload.access_token,
      expiresAt: payload.expires_at,
      providerMode,
      region: payload.region,
    });
    return payload;
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
      await fetcher(`${binding.serverOrigin}/v1/extension/binding`, {
        method: "DELETE",
        headers: {
          Authorization: `Bearer ${binding.accessToken}`,
        },
      });
    }
  } finally {
    await store.clear();
  }
}
