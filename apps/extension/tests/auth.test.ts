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
import { createMemoryBindingStore } from "../src/auth/storage";

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
        JSON.stringify({
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
        }),
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
});
