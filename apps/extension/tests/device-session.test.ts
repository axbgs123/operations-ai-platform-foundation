import { webcrypto } from "node:crypto";

import { describe, expect, it, vi } from "vitest";

import {
  createMemoryDeviceKeyStore,
  type MemoryDeviceKeyStoreState,
  type DeviceKeyStore,
} from "../src/auth/device-key-store";
import {
  createLocalDeviceRegistrationStore,
  createMemoryDeviceRegistrationStore,
  type DeviceRegistration,
  type DeviceRegistrationStore,
} from "../src/auth/device-registration-store";
import { createSessionManager } from "../src/auth/session-renewal";
import { createMemoryBindingStore, type BindingStore, type ExtensionBinding } from "../src/auth/storage";

const cryptoApi = webcrypto as unknown as Crypto;
const now = Date.parse("2030-01-01T00:00:00Z");

const binding = (expiresAt = "2030-01-01T08:00:00Z"): ExtensionBinding => ({
  serverOrigin: "https://ops.example.com",
  webOrigin: "https://app.ops.example.com",
  workspaceId: "00000000-0000-0000-0000-000000000001",
  workspaceName: "运营工作区",
  memberDisplayName: "测试成员",
  accessToken: "renewed-short-token",
  expiresAt,
  providerMode: "mock",
  region: null,
});

const json = (value: unknown, status = 201) =>
  new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });

async function fixture() {
  const keyState: MemoryDeviceKeyStoreState = { record: null };
  const keyStore = createMemoryDeviceKeyStore(cryptoApi, keyState);
  const device = await keyStore.getOrCreate();
  const registration: DeviceRegistration = {
    serverOrigin: "https://ops.example.com",
    webOrigin: "https://app.ops.example.com",
    workspaceId: "00000000-0000-0000-0000-000000000001",
    workspaceName: "运营工作区",
    memberDisplayName: "测试成员",
    providerMode: "mock",
    region: null,
    deviceId: device.deviceId,
    deviceLabel: "Chrome on macOS",
    extensionVersion: "0.3.0",
  };
  const registrations = createMemoryDeviceRegistrationStore();
  await registrations.save(registration);
  return { device, keyStore, keyState, registration, registrations };
}

function renewPayload(deviceId: string, expiresAt = "2030-01-01T08:00:00Z") {
  return {
    access_token: "renewed-short-token",
    token_type: "Bearer",
    workspace_id: "00000000-0000-0000-0000-000000000001",
    member_id: "00000000-0000-0000-0000-000000000002",
    client_id: "operations-capture-extension",
    device_id: deviceId,
    scopes: ["capture:create"],
    issued_at: "2030-01-01T00:00:00Z",
    expires_at: expiresAt,
    workspace_name: "运营工作区",
    member_display_name: "测试成员",
    web_origin: "https://app.ops.example.com",
    provider_mode: "mock",
    region: null,
  };
}

function challenge(deviceId: string) {
  return {
    challenge_id: "00000000-0000-0000-0000-000000000099",
    device_id: deviceId,
    challenge: "Y2hhbGxlbmdlLWJ5dGVz",
    expires_at: "2030-01-01T00:05:00Z",
  };
}

function renewFetcher(deviceId: string, options: { challenge?: unknown; renew?: unknown; pending?: boolean } = {}) {
  return vi.fn(async (input: string | URL | Request) => {
    const url = String(input);
    if (options.pending) return new Promise<Response>(() => undefined);
    if (url.endsWith("/challenge")) return json(options.challenge ?? challenge(deviceId));
    if (url.endsWith("/renew")) return json(options.renew ?? renewPayload(deviceId));
    return new Response(null, { status: 404 });
  }) as unknown as typeof fetch;
}

function manager(
  keyStore: DeviceKeyStore,
  registrations: DeviceRegistrationStore,
  sessionStore: BindingStore,
  fetcher: typeof fetch,
  requestTimeoutMs?: number,
) {
  return createSessionManager({
    keyStore,
    registrations,
    sessionStore,
    fetcher,
    crypto: cryptoApi,
    now: () => now,
    requestTimeoutMs,
  });
}

describe("persistent device sessions", () => {
  it("creates a non-exportable P-256 private key and exports only its public JWK", async () => {
    const keyStore = createMemoryDeviceKeyStore(cryptoApi);
    const device = await keyStore.getOrCreate();

    expect(device.publicJwk).toMatchObject({ kty: "EC", crv: "P-256" });
    await expect(cryptoApi.subtle.exportKey("jwk", device.privateKey)).rejects.toThrow();
    expect(await device.sign(new Uint8Array([1, 2, 3]))).toMatch(/^[A-Za-z0-9_-]+$/);
  });

  it("renews after a service-worker restart without persisting a bearer token", async () => {
    const { keyState, registration, registrations } = await fixture();
    const sessionStore = createMemoryBindingStore();
    const fetcher = renewFetcher(registration.deviceId);
    const firstWorker = manager(createMemoryDeviceKeyStore(cryptoApi, keyState), registrations, sessionStore, fetcher);

    await sessionStore.clear();
    const secondWorker = manager(createMemoryDeviceKeyStore(cryptoApi, keyState), registrations, sessionStore, fetcher);
    const renewed = await secondWorker.ensureFreshBinding();

    expect(renewed.accessToken).toBe("renewed-short-token");
    expect(await firstWorker.ensureFreshBinding()).toEqual(renewed);
    expect(await registrations.load()).not.toHaveProperty("accessToken");
    expect(await registrations.load()).not.toHaveProperty("pairingCode");
  });

  it("keeps registration local records free of tokens and pairing codes", async () => {
    let values: Record<string, unknown> = {};
    const localWrites: Record<string, unknown>[] = [];
    const store = createLocalDeviceRegistrationStore({
      get: async () => values,
      set: async (next) => {
        localWrites.push(next);
        values = next;
      },
      remove: async (key) => { delete values[key]; },
    });
    const { registration } = await fixture();

    await store.save(registration);

    expect(localWrites).toEqual([expect.not.objectContaining({ accessToken: expect.anything(), pairingCode: expect.anything() })]);
    expect(JSON.stringify(values)).not.toContain("accessToken");
    expect(JSON.stringify(values)).not.toContain("pairingCode");
  });

  it.each([
    ["the IndexedDB key is missing", async (keyStore: DeviceKeyStore) => keyStore.clear()],
    ["the server returns a mismatched device id", async () => undefined],
    ["the server returns an invalid challenge", async () => undefined],
    ["a challenge replay is rejected", async () => undefined],
    ["the device has been revoked", async () => undefined],
  ])("fails closed and requires pairing when %s", async (reason, setup) => {
    const { keyStore, registration, registrations } = await fixture();
    const sessions = createMemoryBindingStore();
    await sessions.save(binding());
    await setup(keyStore);
    const response =
      reason === "the server returns a mismatched device id"
        ? { challenge: challenge("00000000-0000-0000-0000-000000000777") }
        : reason === "the server returns an invalid challenge"
          ? { challenge: { ...challenge(registration.deviceId), challenge: 7 } }
          : reason === "a challenge replay is rejected" || reason === "the device has been revoked"
            ? { renew: { detail: "device session invalid" }, renewStatus: 401 }
            : {};
    const fetcher = vi.fn(async (input: string | URL | Request) => {
      const url = String(input);
      if (url.endsWith("/challenge")) return json((response as { challenge?: unknown }).challenge ?? challenge(registration.deviceId));
      return json((response as { renew?: unknown }).renew ?? renewPayload(registration.deviceId), (response as { renewStatus?: number }).renewStatus ?? 201);
    }) as unknown as typeof fetch;

    await expect(manager(keyStore, registrations, sessions, fetcher).ensureFreshBinding(9 * 60 * 60 * 1000)).rejects.toThrow("rebind-required");
    expect(await sessions.load()).toBeNull();
    expect(await registrations.load()).toBeNull();
  });

  it("fails closed after a renewal timeout", async () => {
    vi.useFakeTimers();
    try {
      const { keyStore, registrations } = await fixture();
      const sessions = createMemoryBindingStore();
      const pending = manager(keyStore, registrations, sessions, renewFetcher("unused", { pending: true }), 50).ensureFreshBinding();
      const assertion = expect(pending).rejects.toThrow("rebind-required");
      await vi.advanceTimersByTimeAsync(50);
      await assertion;
      expect(await sessions.load()).toBeNull();
      expect(await registrations.load()).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("renews only when the token is missing or has less than thirty minutes remaining", async () => {
    const { keyStore, registration, registrations } = await fixture();
    const sessions = createMemoryBindingStore();
    const fetcher = renewFetcher(registration.deviceId);
    await sessions.save(binding("2030-01-01T00:31:00Z"));

    await expect(manager(keyStore, registrations, sessions, fetcher).ensureFreshBinding()).resolves.toMatchObject({ accessToken: "renewed-short-token" });
    expect(fetcher).not.toHaveBeenCalled();
    await sessions.save(binding("2030-01-01T00:29:59Z"));
    await manager(keyStore, registrations, sessions, fetcher).ensureFreshBinding();
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("deduplicates concurrent session renewal", async () => {
    const { keyStore, registration, registrations } = await fixture();
    const sessions = createMemoryBindingStore();
    let resolveChallenge!: (response: Response) => void;
    const fetcher = vi.fn((input: string | URL | Request) => {
      if (String(input).endsWith("/challenge")) return new Promise<Response>((resolve) => { resolveChallenge = resolve; });
      return Promise.resolve(json(renewPayload(registration.deviceId)));
    }) as unknown as typeof fetch;
    const sessionManager = manager(keyStore, registrations, sessions, fetcher);
    const first = sessionManager.ensureFreshBinding();
    const second = sessionManager.ensureFreshBinding();
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    resolveChallenge(json(challenge(registration.deviceId)));

    await expect(Promise.all([first, second])).resolves.toEqual([expect.objectContaining({ accessToken: "renewed-short-token" }), expect.objectContaining({ accessToken: "renewed-short-token" })]);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("unlink clears the session, registration, and device key", async () => {
    const { keyStore, registration, registrations } = await fixture();
    const sessions = createMemoryBindingStore();
    await sessions.save(binding());
    const sessionManager = manager(keyStore, registrations, sessions, renewFetcher(registration.deviceId));

    await sessionManager.unlink();

    expect(await sessions.load()).toBeNull();
    expect(await registrations.load()).toBeNull();
    expect(await keyStore.load()).toBeNull();
  });
});
