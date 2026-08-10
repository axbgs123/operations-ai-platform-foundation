import {
  createApiClient,
  type components,
  type operations,
} from "@operations-ai/shared-schemas";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type ExtensionDeviceRead = components["schemas"]["ExtensionDeviceRead"];
type ListExtensionDevicesOperation =
  operations["list_extension_devices_v1_workspaces__workspace_id__extension_devices_get"];
type RevokeExtensionDeviceOperation =
  operations["revoke_extension_device_v1_workspaces__workspace_id__extension_devices__device_id__delete"];
type ListExtensionDevicesPath = NonNullable<
  ListExtensionDevicesOperation["parameters"]["path"]
>;
type ListExtensionDevicesHeaders = NonNullable<
  ListExtensionDevicesOperation["parameters"]["header"]
>;
type RevokeExtensionDevicePath = NonNullable<
  RevokeExtensionDeviceOperation["parameters"]["path"]
>;
type RevokeExtensionDeviceHeaders = NonNullable<
  RevokeExtensionDeviceOperation["parameters"]["header"]
>;

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
  const path: ListExtensionDevicesPath = { workspace_id: workspaceId };
  const header: ListExtensionDevicesHeaders = { "X-CSRF-Token": csrfToken };
  const { data, response } = await createApiClient(API_URL).GET(
    "/v1/workspaces/{workspace_id}/extension-devices",
    {
      params: { header, path },
    },
  );
  if (!response.ok || !data) {
    throw new ExtensionDeviceApiError(response.status, "list");
  }
  return data;
}

export async function revokeExtensionDevice(
  workspaceId: string,
  deviceId: string,
  csrfToken: string,
): Promise<void> {
  const path: RevokeExtensionDevicePath = {
    device_id: deviceId,
    workspace_id: workspaceId,
  };
  const header: RevokeExtensionDeviceHeaders = { "X-CSRF-Token": csrfToken };
  const { response } = await createApiClient(API_URL).DELETE(
    "/v1/workspaces/{workspace_id}/extension-devices/{device_id}",
    {
      params: { header, path },
    },
  );
  if (!response.ok) throw new ExtensionDeviceApiError(response.status, "revoke");
}
