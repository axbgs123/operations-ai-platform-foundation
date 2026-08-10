import type { components } from "@operations-ai/shared-schemas";

import type { DeviceKeyStore } from "./device-key-store";
import type { DeviceRegistration, DeviceRegistrationStore } from "./device-registration-store";
import { isBindingFresh, parseExtensionBinding, type BindingStore, type ExtensionBinding } from "./storage";

type ChallengeResponse = components["schemas"]["ExtensionSessionChallengeRead"];
type RenewResponse = components["schemas"]["ExtensionPairResponse"];

export interface SessionManager {
  ensureFreshBinding(minRemainingMs?: number): Promise<ExtensionBinding>;
  unlink(): Promise<void>;
}

export type SessionManagerDependencies = {
  keyStore: DeviceKeyStore;
  registrations: DeviceRegistrationStore;
  sessionStore: BindingStore;
  fetcher: typeof fetch;
  crypto?: Crypto;
  now?: () => number;
  requestTimeoutMs?: number;
  clientId?: "operations-capture-extension";
};

const defaultMinRemainingMs = 30 * 60 * 1000;
const defaultRequestTimeoutMs = 10_000;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

function decodeBase64Url(value: string): Uint8Array | null {
  if (!/^[A-Za-z0-9_-]+$/.test(value)) return null;
  try {
    const padded = value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - value.length % 4) % 4);
    const binary = atob(padded);
    return Uint8Array.from(binary, (character) => character.charCodeAt(0));
  } catch {
    return null;
  }
}

function validChallenge(value: unknown, deviceId: string, now: number): value is ChallengeResponse {
  return isRecord(value) &&
    typeof value.challenge_id === "string" && value.challenge_id !== "" &&
    value.device_id === deviceId &&
    typeof value.challenge === "string" && decodeBase64Url(value.challenge) !== null &&
    typeof value.expires_at === "string" && Number.isFinite(Date.parse(value.expires_at)) &&
    Date.parse(value.expires_at) > now;
}

function bindingFromRenewal(value: unknown, registration: DeviceRegistration): ExtensionBinding | null {
  if (!isRecord(value) || value.device_id !== registration.deviceId) return null;
  const binding = parseExtensionBinding({
    serverOrigin: registration.serverOrigin,
    webOrigin: value.web_origin,
    workspaceId: value.workspace_id,
    workspaceName: value.workspace_name,
    memberDisplayName: value.member_display_name,
    accessToken: value.access_token,
    expiresAt: value.expires_at,
    providerMode: value.provider_mode,
    region: value.region,
  });
  if (!binding || binding.workspaceId !== registration.workspaceId || binding.webOrigin !== registration.webOrigin) return null;
  return binding;
}

export function createSessionManager(dependencies: SessionManagerDependencies): SessionManager {
  const cryptoApi = dependencies.crypto ?? crypto;
  const now = dependencies.now ?? Date.now;
  const timeoutMs = dependencies.requestTimeoutMs ?? defaultRequestTimeoutMs;
  const clientId = dependencies.clientId ?? "operations-capture-extension";
  let inFlight: Promise<ExtensionBinding> | null = null;

  const failClosed = async (): Promise<never> => {
    await Promise.allSettled([
      dependencies.sessionStore.clear(),
      dependencies.registrations.clear(),
      dependencies.keyStore.clear(),
    ]);
    throw new Error("rebind-required");
  };

  const request = async (url: string, body: unknown): Promise<Response> => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      return await Promise.race([
        dependencies.fetcher(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
          signal: controller.signal,
        }),
        new Promise<Response>((_resolve, reject) => {
          timer = setTimeout(() => {
            controller.abort();
            reject(new Error("session-renewal-timeout"));
          }, timeoutMs);
        }),
      ]);
    } finally {
      if (timer !== undefined) clearTimeout(timer);
    }
  };

  const renew = async (): Promise<ExtensionBinding> => {
    try {
      const registration = await dependencies.registrations.load();
      const device = await dependencies.keyStore.load();
      if (!registration || !device || registration.deviceId !== device.deviceId) return failClosed();
      const challengeResponse = await request(`${registration.serverOrigin}/v1/extension/session/challenge`, {
        device_id: registration.deviceId,
        client_id: clientId,
      });
      if (!challengeResponse.ok) return failClosed();
      const challengeValue: unknown = await challengeResponse.json();
      if (!validChallenge(challengeValue, registration.deviceId, now())) return failClosed();
      const challengeBytes = decodeBase64Url(challengeValue.challenge);
      if (!challengeBytes) return failClosed();
      const signature = await device.sign(challengeBytes);
      const renewalResponse = await request(`${registration.serverOrigin}/v1/extension/session/renew`, {
        device_id: registration.deviceId,
        challenge_id: challengeValue.challenge_id,
        signature,
      });
      if (!renewalResponse.ok) return failClosed();
      const binding = bindingFromRenewal(await renewalResponse.json() as RenewResponse, registration);
      if (!binding) return failClosed();
      await dependencies.sessionStore.save(binding);
      return binding;
    } catch {
      return failClosed();
    }
  };

  return {
    async ensureFreshBinding(minRemainingMs = defaultMinRemainingMs) {
      const current = await dependencies.sessionStore.load();
      if (current && isBindingFresh(current, now(), minRemainingMs)) return current;
      if (!inFlight) {
        inFlight = renew().finally(() => { inFlight = null; });
      }
      return inFlight;
    },
    async unlink() {
      const outcomes = await Promise.allSettled([
        dependencies.sessionStore.clear(),
        dependencies.registrations.clear(),
        dependencies.keyStore.clear(),
      ]);
      if (outcomes.some((outcome) => outcome.status === "rejected")) throw new Error("unlink-failed");
    },
  };
}
