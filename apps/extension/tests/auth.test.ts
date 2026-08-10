import { describe, expect, it } from "vitest";

import {
  clearBinding,
  normalizeServerOrigin,
  validateServerOrigin,
} from "../src/auth/server";
import {
  pairExtension,
  bindingDisclosure,
  revokeExtension,
} from "../src/auth/client";
import {
  createMemoryBindingStore,
  createSessionBindingStore,
} from "../src/auth/storage";

const validPairResponse = {
  access_token: "opaque-session-token",
  token_type: "Bearer",
  workspace_id: "00000000-0000-0000-0000-000000000001",
  member_id: "00000000-0000-0000-0000-000000000002",
  client_id: "extension-test",
  scopes: ["capture:create", "capture:upload", "capture:read"],
  issued_at: "2026-07-23T00:00:00Z",
  expires_at: "2026-07-23T00:15:00Z",
  workspace_name: "运营工作区",
  member_display_name: "测试成员",
  web_origin: "https://app.ops.example.com",
  provider_mode: "mock",
  region: null,
};

describe("extension binding security", () => {
  it("allows HTTPS origins and local development loopback only", () => {
    expect(validateServerOrigin("https://ops.example.com")).toEqual({
      ok: true,
      origin: "https://ops.example.com",
    });
    expect(validateServerOrigin("http://localhost:8100").ok).toBe(true);
    expect(validateServerOrigin("http://127.0.0.1:8100").ok).toBe(true);
    for (const value of [
      "http://ops.example.com",
      "ftp://ops.example.com",
      "file:///tmp/ops",
      "javascript:alert(1)",
      "data:text/plain,ops",
      "https://user:password@ops.example.com",
      "https://ops.example.com/#fragment",
      "https://127.0.0.1.evil.example.com",
    ]) {
      expect(validateServerOrigin(value).ok).toBe(false);
    }
    expect(normalizeServerOrigin("HTTPS://ops.example.com/")).toBe(
      "https://ops.example.com",
    );
  });

  it("keeps only a short-lived token in session storage and clears all binding state", async () => {
    const store = createMemoryBindingStore();
    await store.save({
      serverOrigin: "https://ops.example.com",
      webOrigin: "https://app.ops.example.com",
      workspaceId: "00000000-0000-0000-0000-000000000001",
      workspaceName: "运营工作区",
      memberDisplayName: "测试成员",
      accessToken: "opaque-short-lived-token",
      expiresAt: "2026-07-23T00:01:00Z",
      providerMode: "mock",
      region: null,
    });
    expect(await store.load()).toEqual({
      serverOrigin: "https://ops.example.com",
      webOrigin: "https://app.ops.example.com",
      workspaceId: "00000000-0000-0000-0000-000000000001",
      workspaceName: "运营工作区",
      memberDisplayName: "测试成员",
      accessToken: "opaque-short-lived-token",
      expiresAt: "2026-07-23T00:01:00Z",
      providerMode: "mock",
      region: null,
    });
    await clearBinding(store);
    expect(await store.load()).toBeNull();
  });

  it.each([
    ["old schema", { serverOrigin: "https://ops.example.com" }],
    ["missing field", { serverOrigin: "https://ops.example.com", webOrigin: "https://app.ops.example.com", workspaceId: "00000000-0000-0000-0000-000000000001", workspaceName: "运营工作区", memberDisplayName: "测试成员", accessToken: "token", providerMode: "mock", region: null }],
    ["wrong field type", { serverOrigin: "https://ops.example.com", webOrigin: "https://app.ops.example.com", workspaceId: 1, workspaceName: "运营工作区", memberDisplayName: "测试成员", accessToken: "token", expiresAt: "2026-07-23T00:15:00Z", providerMode: "mock", region: null }],
    ["invalid expiry", { serverOrigin: "https://ops.example.com", webOrigin: "https://app.ops.example.com", workspaceId: "00000000-0000-0000-0000-000000000001", workspaceName: "运营工作区", memberDisplayName: "测试成员", accessToken: "token", expiresAt: "not-a-date", providerMode: "mock", region: null }],
    ["unexpected secret", { serverOrigin: "https://ops.example.com", webOrigin: "https://app.ops.example.com", workspaceId: "00000000-0000-0000-0000-000000000001", workspaceName: "运营工作区", memberDisplayName: "测试成员", accessToken: "token", expiresAt: "2026-07-23T00:15:00Z", providerMode: "mock", region: null, refreshToken: "must-not-persist" }],
  ])("clears invalid session binding: %s", async (_name, stored) => {
    let values: Record<string, unknown> = { extensionBinding: stored };
    const remove = async (key: string) => { delete values[key]; };
    const store = createSessionBindingStore({
      get: async () => values,
      set: async (next) => { values = next; },
      remove,
    });
    await expect(store.load()).resolves.toBeNull();
    expect(values).toEqual({});
  });

  it("exchanges a pairing code and clears it from memory after both outcomes", async () => {
    const store = createMemoryBindingStore();
    let pairingCode = "123456";
    const requests: Array<{ url: string; body: unknown }> = [];
    const fetcher: typeof fetch = async (input, init) => {
      requests.push({
        url: String(input),
        body: JSON.parse(String(init?.body)),
      });
      return new Response(
        JSON.stringify(validPairResponse),
        { status: 201, headers: { "Content-Type": "application/json" } },
      );
    };

    await pairExtension(
      {
        serverOrigin: "https://ops.example.com",
        pairingCode,
        clientId: "extension-test",
      },
      { fetcher, store, clearPairingCode: () => (pairingCode = "") },
    );

    expect(requests).toEqual([
      {
        url: "https://ops.example.com/v1/extension/pair",
        body: { pairing_code: "123456", client_id: "extension-test" },
      },
    ]);
    expect(pairingCode).toBe("");
    expect(await store.load()).toEqual({
      serverOrigin: "https://ops.example.com",
      webOrigin: "https://app.ops.example.com",
      workspaceId: "00000000-0000-0000-0000-000000000001",
      workspaceName: "运营工作区",
      memberDisplayName: "测试成员",
      accessToken: "opaque-session-token",
      expiresAt: "2026-07-23T00:15:00Z",
      providerMode: "mock",
      region: null,
    });

    let failedPairingCode = "654321";
    await expect(
      pairExtension(
        {
          serverOrigin: "https://ops.example.com",
          pairingCode: failedPairingCode,
          clientId: "extension-test",
        },
        {
          fetcher: async () =>
            new Response("rejected", { status: 401 }),
          store,
          clearPairingCode: () => (failedPairingCode = ""),
        },
      ),
    ).rejects.toThrow("服务器配对失败");
    expect(failedPairingCode).toBe("");
  });

  it.each([
    ["missing disclosure", { ...validPairResponse, workspace_name: undefined }],
    ["invalid web origin", { ...validPairResponse, web_origin: "http://app.ops.example.com" }],
    ["invalid expiry", { ...validPairResponse, expires_at: "not-a-date" }],
    ["unknown provider", { ...validPairResponse, provider_mode: "future-provider" }],
  ])("rejects invalid successful pairing response without saving: %s", async (_name, payload) => {
    const store = createMemoryBindingStore();
    let cleared = 0;
    await expect(pairExtension(
      { serverOrigin: "https://ops.example.com", pairingCode: "123456", clientId: "extension-test" },
      {
        fetcher: async () => new Response(JSON.stringify(payload), { status: 201 }),
        store,
        clearPairingCode: () => { cleared += 1; },
      },
    )).rejects.toThrow("服务器配对失败");
    expect(await store.load()).toBeNull();
    expect(cleared).toBe(1);
  });

  it.each([
    "http://ops.example.com",
    "https://ops.example.com/path",
    "https://user:password@ops.example.com",
    "https://ops.example.com/#fragment",
    "https://127.0.0.1.evil.example.com",
  ])("clears the pairing code exactly once for invalid origin %s", async (serverOrigin) => {
    const store = createMemoryBindingStore();
    let cleared = 0;
    await expect(pairExtension(
      { serverOrigin, pairingCode: "123456", clientId: "extension-test" },
      { fetcher: async () => new Response(null, { status: 201 }), store, clearPairingCode: () => { cleared += 1; } },
    )).rejects.toThrow("服务器配对失败");
    expect(cleared).toBe(1);
    expect(await store.load()).toBeNull();
  });

  it("always explains destination, processing mode, and human confirmation", () => {
    expect(
      bindingDisclosure("https://ops.example.com", "Mock OCR/视觉处理"),
    ).toEqual([
      "截图将上传到：https://ops.example.com",
      "处理方式：Mock OCR/视觉处理",
      "识别数据仍需人工确认",
    ]);
  });

  it("revokes on the bound server before clearing session state", async () => {
    const store = createMemoryBindingStore();
    await store.save({
      serverOrigin: "https://ops.example.com",
      webOrigin: "https://app.ops.example.com",
      workspaceId: "00000000-0000-0000-0000-000000000001",
      workspaceName: "运营工作区",
      memberDisplayName: "测试成员",
      accessToken: "revocable-session-token",
      expiresAt: "2026-07-23T00:15:00Z",
      providerMode: "mock",
      region: null,
    });
    const requests: Array<{ url: string; authorization: string | null }> = [];

    await revokeExtension(store, async (input, init) => {
      requests.push({
        url: String(input),
        authorization: new Headers(init?.headers).get("Authorization"),
      });
      return new Response(null, { status: 204 });
    });

    expect(requests).toEqual([
      {
        url: "https://ops.example.com/v1/extension/binding",
        authorization: "Bearer revocable-session-token",
      },
    ]);
    expect(await store.load()).toBeNull();
  });

  it.each([
    ["fetch rejection", async () => { throw new Error("offline"); }],
    ["non-2xx response", async () => new Response(null, { status: 503 })],
  ])("clears local binding when revocation has %s", async (_name, fetcher) => {
    const store = createMemoryBindingStore();
    await store.save({
      serverOrigin: "https://ops.example.com", webOrigin: "https://app.ops.example.com", workspaceId: "00000000-0000-0000-0000-000000000001", workspaceName: "运营工作区", memberDisplayName: "测试成员", accessToken: "token", expiresAt: "2026-07-23T00:15:00Z", providerMode: "mock", region: null,
    });
    await expect(revokeExtension(store, fetcher)).rejects.toThrow();
    expect(await store.load()).toBeNull();
  });
});
