import { afterEach, beforeEach, expect, test, vi } from "vitest";

const GET = vi.hoisted(() => vi.fn());
const DELETE = vi.hoisted(() => vi.fn());
const createApiClient = vi.hoisted(() => vi.fn(() => ({ DELETE, GET })));

vi.mock("@operations-ai/shared-schemas", async (importOriginal) => ({
  ...await importOriginal<typeof import("@operations-ai/shared-schemas")>(),
  createApiClient,
}));

import {
  listExtensionDevices,
  revokeExtensionDevice,
} from "./extension-device-api";

beforeEach(() => {
  GET.mockReset();
  DELETE.mockReset();
  createApiClient.mockClear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

test("lists a workspace's devices through the generated client with typed path and CSRF header", async () => {
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
  GET.mockResolvedValue({
    data: devices,
    response: { ok: true, status: 200 },
  });

  await expect(listExtensionDevices("workspace-1", "csrf-token")).resolves.toEqual(devices);
  expect(createApiClient).toHaveBeenCalledWith("http://localhost:8000");
  expect(GET).toHaveBeenCalledWith(
    "/v1/workspaces/{workspace_id}/extension-devices",
    {
      params: {
        header: { "X-CSRF-Token": "csrf-token" },
        path: { workspace_id: "workspace-1" },
      },
    },
  );
});

test("revokes a device through the generated client with typed path and CSRF header", async () => {
  DELETE.mockResolvedValue({
    data: undefined,
    response: { ok: true, status: 204 },
  });

  await expect(revokeExtensionDevice("workspace-1", "device-1", "csrf-token")).resolves.toBeUndefined();
  expect(createApiClient).toHaveBeenCalledWith("http://localhost:8000");
  expect(DELETE).toHaveBeenCalledWith(
    "/v1/workspaces/{workspace_id}/extension-devices/{device_id}",
    {
      params: {
        header: { "X-CSRF-Token": "csrf-token" },
        path: { device_id: "device-1", workspace_id: "workspace-1" },
      },
    },
  );
});
