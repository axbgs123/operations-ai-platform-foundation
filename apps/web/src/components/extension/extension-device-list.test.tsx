import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { ExtensionDeviceList } from "./extension-device-list";

const listExtensionDevices = vi.hoisted(() => vi.fn());
const revokeExtensionDevice = vi.hoisted(() => vi.fn());
const ExtensionDeviceApiError = vi.hoisted(() => class extends Error {
  constructor(readonly status: number) {
    super(status === 403
      ? "仅管理员可以管理已连接设备。"
      : status === 404
        ? "无法打开这组设备。请从当前工作区的设置页面重试。"
        : "暂时无法加载设备，请稍后重试。");
  }
});

vi.mock("@/lib/extension-device-api", () => ({
  ExtensionDeviceApiError,
  listExtensionDevices,
  revokeExtensionDevice,
}));

const device = {
  browser: "Chrome",
  created_at: "2026-08-10T01:00:00.000Z",
  device_id: "device-1",
  extension_version: "0.3.0",
  fingerprint: "private-fingerprint",
  label: "运营电脑",
  last_used_at: "2026-08-10T02:00:00.000Z",
  public_jwk: { kty: "EC", crv: "P-256", x: "private-x", y: "private-y" },
  revoked_at: null,
  status: "active" as const,
  token: "private-token",
};

beforeEach(() => {
  listExtensionDevices.mockReset();
  revokeExtensionDevice.mockReset();
  sessionStorage.setItem("workspace_csrf", "csrf-token");
  Object.defineProperty(window.navigator, "platform", {
    configurable: true,
    value: "MacIntel",
  });
});

afterEach(() => {
  cleanup();
  sessionStorage.clear();
});

test("shows the actual shortcut and only safe device fields before an admin revokes", async () => {
  listExtensionDevices.mockResolvedValue([device]);
  revokeExtensionDevice.mockResolvedValue(undefined);
  const user = userEvent.setup();
  render(<ExtensionDeviceList role="admin" workspaceId="workspace-1" />);

  expect(await screen.findByText("Command + Shift + 8")).toBeVisible();
  expect(screen.getByText("运营电脑")).toBeVisible();
  expect(screen.getByText("Chrome · 扩展 0.3.0")).toBeVisible();
  expect(document.body).not.toHaveTextContent("private-fingerprint");
  expect(document.body).not.toHaveTextContent("private-token");
  expect(document.body).not.toHaveTextContent("private-x");
  await user.click(screen.getByRole("button", { name: "撤销此设备" }));
  expect(screen.getByRole("dialog", { name: "确认撤销设备" })).toBeVisible();
  await user.click(screen.getByRole("button", { name: "确认撤销" }));

  expect(revokeExtensionDevice).toHaveBeenCalledWith("workspace-1", "device-1", "csrf-token");
  expect(await screen.findByText("已撤销")).toBeVisible();
});

test("lets an admin retry a failed load without exposing server details", async () => {
  listExtensionDevices
    .mockRejectedValueOnce(new Error("private backend details"))
    .mockResolvedValueOnce([device]);
  const user = userEvent.setup();
  render(<ExtensionDeviceList role="admin" workspaceId="workspace-1" />);

  expect(await screen.findByRole("alert")).toHaveTextContent("暂时无法加载设备，请稍后重试。");
  expect(document.body).not.toHaveTextContent("private backend details");
  await user.click(screen.getByRole("button", { name: "重试加载设备" }));
  expect(await screen.findByText("运营电脑")).toBeVisible();
});

test("keeps a failed revocation actionable without exposing its server details", async () => {
  listExtensionDevices.mockResolvedValue([device]);
  revokeExtensionDevice
    .mockRejectedValueOnce(new Error("private revoke failure"))
    .mockResolvedValueOnce(undefined);
  const user = userEvent.setup();
  render(<ExtensionDeviceList role="admin" workspaceId="workspace-1" />);

  await screen.findByText("运营电脑");
  await user.click(screen.getByRole("button", { name: "撤销此设备" }));
  await user.click(screen.getByRole("button", { name: "确认撤销" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("暂时无法撤销此设备，请稍后重试。");
  expect(document.body).not.toHaveTextContent("private revoke failure");
  await user.click(screen.getByRole("button", { name: "重试撤销此设备" }));

  expect(revokeExtensionDevice).toHaveBeenCalledTimes(2);
  expect(await screen.findByText("已撤销")).toBeVisible();
});

test("explains a cross-workspace 404 without revealing whether another workspace exists", async () => {
  listExtensionDevices.mockRejectedValue(new ExtensionDeviceApiError(404));
  render(<ExtensionDeviceList role="admin" workspaceId="workspace-1" />);

  expect(await screen.findByRole("alert")).toHaveTextContent("无法打开这组设备。请从当前工作区的设置页面重试。");
  expect(document.body).not.toHaveTextContent("workspace-1");
});

test("downgrades a loaded admin list to safe guidance after a later list 403", async () => {
  listExtensionDevices
    .mockResolvedValueOnce([device])
    .mockRejectedValueOnce(new ExtensionDeviceApiError(403));
  const view = render(<ExtensionDeviceList role="admin" workspaceId="workspace-1" />);

  await screen.findByText("运营电脑");
  view.rerender(<ExtensionDeviceList role="admin" workspaceId="workspace-2" />);
  expect(await screen.findByText("保持连接，直到你或管理员解除")).toBeVisible();
  expect(screen.queryByText("运营电脑")).toBeNull();
  expect(screen.queryByRole("button", { name: "撤销此设备" })).toBeNull();
  expect(screen.queryByRole("button", { name: "重试加载设备" })).toBeNull();

  view.rerender(<ExtensionDeviceList role="admin" workspaceId="workspace-3" />);
  expect(listExtensionDevices).toHaveBeenCalledTimes(2);
});

test("downgrades a loaded admin list after revocation receives 403", async () => {
  listExtensionDevices.mockResolvedValue([device]);
  revokeExtensionDevice.mockRejectedValue(new ExtensionDeviceApiError(403));
  const user = userEvent.setup();
  render(<ExtensionDeviceList role="admin" workspaceId="workspace-1" />);

  await screen.findByText("运营电脑");
  await user.click(screen.getByRole("button", { name: "撤销此设备" }));
  await user.click(screen.getByRole("button", { name: "确认撤销" }));

  expect(await screen.findByText("保持连接，直到你或管理员解除")).toBeVisible();
  expect(screen.queryByRole("dialog", { name: "确认撤销设备" })).toBeNull();
  expect(screen.queryByText("运营电脑")).toBeNull();
  expect(screen.queryByRole("button", { name: "重试撤销此设备" })).toBeNull();
});

test.each(["editor", "viewer"] as const)("shows %s safe connection guidance without device actions", async (role) => {
  render(<ExtensionDeviceList role={role} workspaceId="workspace-1" />);

  expect(screen.getByText("保持连接，直到你或管理员解除")).toBeVisible();
  expect(screen.queryByRole("button", { name: "撤销此设备" })).toBeNull();
  expect(listExtensionDevices).not.toHaveBeenCalled();
});
