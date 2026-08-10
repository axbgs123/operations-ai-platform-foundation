import { afterEach, expect, test, vi } from "vitest";

import {
  createExtensionPairingCode,
  ExtensionPairingApiError,
} from "./extension-pairing-api";

const pairing = {
  expires_at: "2026-08-10T01:05:00.000Z",
  pairing_code: "ABCD2345",
  workspace_id: "workspace-1",
  workspace_name: "运营工作区",
};

afterEach(() => vi.unstubAllGlobals());

test("posts a pairing request with session credentials and CSRF", async () => {
  const fetchMock = vi.fn().mockResolvedValue({
    json: () => Promise.resolve(pairing),
    ok: true,
    status: 200,
  } as Response);
  vi.stubGlobal("fetch", fetchMock);

  await expect(createExtensionPairingCode("workspace-1", "csrf-token")).resolves.toEqual(pairing);
  expect(fetchMock).toHaveBeenCalledWith(
    "http://localhost:8000/v1/workspaces/workspace-1/extension-pairing-codes",
    {
      credentials: "include",
      headers: { "X-CSRF-Token": "csrf-token" },
      method: "POST",
    },
  );
});

test.each([
  [401, "登录状态已失效，请重新登录后重试。"],
  [403, "当前角色无权生成连接码。"],
  [404, "工作区不存在或已不可用。"],
  [429, "生成请求过于频繁，请稍后重试。"],
  [500, "服务暂时不可用，请稍后重试。"],
  [503, "服务暂时不可用，请稍后重试。"],
])("maps %i without reading an error response body", async (status, message) => {
  const sentinel = new Error("ERROR_BODY_WAS_READ");
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    json: () => { throw sentinel; },
    ok: false,
    status,
    text: () => { throw sentinel; },
  } as unknown as Response));

  await expect(createExtensionPairingCode("workspace-1", "csrf-token")).rejects.toMatchObject({
    message,
    name: "ExtensionPairingApiError",
    status,
  } satisfies Partial<ExtensionPairingApiError>);
});
