import { afterEach, expect, test, vi } from "vitest";

import {
  listExtensionDevices,
  revokeExtensionDevice,
} from "./extension-device-api";

afterEach(() => {
  vi.unstubAllGlobals();
});

test("lists a workspace's devices with the required CSRF header", async () => {
  const devices = [{
    browser: "Chrome",
    created_at: "2026-08-10T01:00:00.000Z",
    device_id: "device-1",
    extension_version: "0.3.0",
    label: "运营电脑",
    last_used_at: "2026-08-10T02:00:00.000Z",
    revoked_at: null,
    status: "active" as const,
  }];
  const fetchMock = vi.fn().mockResolvedValue({
    json: async () => devices,
    ok: true,
  });
  vi.stubGlobal("fetch", fetchMock);

  await expect(listExtensionDevices("workspace-1", "csrf-token")).resolves.toEqual(devices);
  expect(fetchMock).toHaveBeenCalledWith(
    "http://localhost:8000/v1/workspaces/workspace-1/extension-devices",
    {
      credentials: "include",
      headers: { "X-CSRF-Token": "csrf-token" },
    },
  );
});

test("revokes a device with session credentials and CSRF", async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true });
  vi.stubGlobal("fetch", fetchMock);

  await expect(revokeExtensionDevice("workspace-1", "device-1", "csrf-token")).resolves.toBeUndefined();
  expect(fetchMock).toHaveBeenCalledWith(
    "http://localhost:8000/v1/workspaces/workspace-1/extension-devices/device-1",
    {
      credentials: "include",
      headers: { "X-CSRF-Token": "csrf-token" },
      method: "DELETE",
    },
  );
});
