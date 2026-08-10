import type { components } from "@operations-ai/shared-schemas";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type ExtensionPairingCodeRead =
  components["schemas"]["ExtensionPairingCodeRead"];

export class ExtensionPairingApiError extends Error {
  constructor(readonly status: number) {
    super(pairingErrorMessage(status));
    this.name = "ExtensionPairingApiError";
  }
}

function pairingErrorMessage(status: number): string {
  if (status === 401) return "登录状态已失效，请重新登录后重试。";
  if (status === 403) return "当前角色无权生成连接码。";
  if (status === 404) return "工作区不存在或已不可用。";
  if (status === 429) return "生成请求过于频繁，请稍后重试。";
  if (status >= 500) return "服务暂时不可用，请稍后重试。";
  return "暂时无法生成连接码，请稍后重试。";
}

export async function createExtensionPairingCode(
  workspaceId: string,
  csrfToken: string,
): Promise<ExtensionPairingCodeRead> {
  const response = await fetch(
    `${API_URL}/v1/workspaces/${workspaceId}/extension-pairing-codes`,
    {
      method: "POST",
      credentials: "include",
      headers: { "X-CSRF-Token": csrfToken },
    },
  );
  if (!response.ok) throw new ExtensionPairingApiError(response.status);
  return response.json() as Promise<ExtensionPairingCodeRead>;
}
