import type { components } from "@operations-ai/shared-schemas";

import { normalizeServerOrigin } from "./server";
import type { BindingStore } from "./storage";

type BindResponse = components["schemas"]["ExtensionBindResponse"];

export type BindingInput = {
  serverOrigin: string;
  inviteCode: string;
  clientId: string;
};

export type BindingDependencies = {
  fetcher: typeof fetch;
  store: BindingStore;
  clearInvite(): void;
  requestOriginPermission?(originPattern: string): Promise<boolean>;
};

export async function bindExtension(
  input: BindingInput,
  dependencies: BindingDependencies,
): Promise<BindResponse> {
  const serverOrigin = normalizeServerOrigin(input.serverOrigin);
  try {
    if (
      dependencies.requestOriginPermission &&
      !(await dependencies.requestOriginPermission(`${serverOrigin}/*`))
    ) {
      throw new Error("服务器权限未授权");
    }
    const response = await dependencies.fetcher(
      `${serverOrigin}/v1/extension/bind`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": crypto.randomUUID(),
          "X-Extension-Client": input.clientId,
        },
        body: JSON.stringify({
          invite_code: input.inviteCode,
          client_id: input.clientId,
        }),
      },
    );
    if (!response.ok) throw new Error("服务器绑定失败");
    const payload = (await response.json()) as BindResponse;
    await dependencies.store.save({
      serverOrigin,
      accessToken: payload.access_token,
      expiresAt: payload.expires_at,
    });
    return payload;
  } catch {
    throw new Error("服务器绑定失败");
  } finally {
    dependencies.clearInvite();
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
