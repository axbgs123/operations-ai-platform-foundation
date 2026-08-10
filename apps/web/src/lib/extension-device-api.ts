import type { components } from "@operations-ai/shared-schemas";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type ExtensionDeviceRead = components["schemas"]["ExtensionDeviceRead"];

export class ExtensionDeviceApiError extends Error {
  constructor(readonly status: number, operation: "list" | "revoke") {
    super(extensionDeviceErrorMessage(status, operation));
    this.name = "ExtensionDeviceApiError";
  }
}

function extensionDeviceErrorMessage(
  status: number,
  operation: "list" | "revoke",
): string {
  if (status === 401) return "登录状态已失效，请重新登录后重试。";
  if (status === 403) return "仅管理员可以管理已连接设备。";
  if (status === 404) return "无法打开这组设备。请从当前工作区的设置页面重试。";
  if (status >= 500) {
    return operation === "list"
      ? "暂时无法加载设备，请稍后重试。"
      : "暂时无法撤销此设备，请稍后重试。";
  }
  return operation === "list"
    ? "暂时无法加载设备，请稍后重试。"
    : "暂时无法撤销此设备，请稍后重试。";
}

export async function listExtensionDevices(
  workspaceId: string,
  csrfToken: string,
): Promise<ExtensionDeviceRead[]> {
  const response = await fetch(
    `${API_URL}/v1/workspaces/${workspaceId}/extension-devices`,
    {
      credentials: "include",
      headers: { "X-CSRF-Token": csrfToken },
    },
  );
  if (!response.ok) throw new ExtensionDeviceApiError(response.status, "list");
  return response.json() as Promise<ExtensionDeviceRead[]>;
}

export async function revokeExtensionDevice(
  workspaceId: string,
  deviceId: string,
  csrfToken: string,
): Promise<void> {
  const response = await fetch(
    `${API_URL}/v1/workspaces/${workspaceId}/extension-devices/${deviceId}`,
    {
      credentials: "include",
      headers: { "X-CSRF-Token": csrfToken },
      method: "DELETE",
    },
  );
  if (!response.ok) throw new ExtensionDeviceApiError(response.status, "revoke");
}
