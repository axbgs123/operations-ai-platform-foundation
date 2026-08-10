import type { components } from "@operations-ai/shared-schemas";

import type { DeviceKeyStore, StoredDeviceSigner } from "./device-key-store";
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
  now?: () => number;
  requestTimeoutMs?: number;
  clientId?: "operations-capture-extension";
};

const defaultMinRemainingMs = 30 * 60 * 1000;
const defaultRequestTimeoutMs = 10_000;

class TerminalSessionError extends Error {}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

function decodeBase64Url(value: string): Uint8Array | null {
  if (!/^[A-Za-z0-9_-]+$/.test(value)) return null;
  try {
    const padded = value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - value.length % 4) % 4);
    return Uint8Array.from(atob(padded), (character) => character.charCodeAt(0));
  } catch { return null; }
}

function validChallenge(value: unknown, deviceId: string, currentTime: number): value is ChallengeResponse {
  return isRecord(value) && typeof value.challenge_id === "string" && value.challenge_id !== "" &&
    value.device_id === deviceId && typeof value.challenge === "string" && decodeBase64Url(value.challenge) !== null &&
    typeof value.expires_at === "string" && Number.isFinite(Date.parse(value.expires_at)) && Date.parse(value.expires_at) > currentTime;
}

function bindingFromRenewal(value: unknown, registration: DeviceRegistration): ExtensionBinding | null {
  if (!isRecord(value) || value.device_id !== registration.deviceId) return null;
  const binding = parseExtensionBinding({
    serverOrigin: registration.serverOrigin, webOrigin: value.web_origin, workspaceId: value.workspace_id,
    workspaceName: value.workspace_name, memberDisplayName: value.member_display_name,
    accessToken: value.access_token, expiresAt: value.expires_at, providerMode: value.provider_mode, region: value.region,
  });
  return binding && binding.workspaceId === registration.workspaceId && binding.webOrigin === registration.webOrigin
    ? binding : null;
}

function sameIdentity(binding: ExtensionBinding, registration: DeviceRegistration, device: StoredDeviceSigner): boolean {
  return binding.serverOrigin === registration.serverOrigin && binding.webOrigin === registration.webOrigin &&
    binding.workspaceId === registration.workspaceId && registration.deviceId === device.deviceId;
}

export function createSessionManager(dependencies: SessionManagerDependencies): SessionManager {
  const now = dependencies.now ?? Date.now;
  const timeoutMs = dependencies.requestTimeoutMs ?? defaultRequestTimeoutMs;
  const clientId = dependencies.clientId ?? "operations-capture-extension";
  let inFlight: Promise<ExtensionBinding> | null = null;
  let generation = 0;
  let activeController: AbortController | null = null;

  const terminal = async (): Promise<never> => {
    await Promise.allSettled([dependencies.sessionStore.clear(), dependencies.registrations.clear(), dependencies.keyStore.clear()]);
    throw new Error("rebind-required");
  };
  const retryable = async (): Promise<never> => {
    await Promise.allSettled([dependencies.sessionStore.clear()]);
    throw new Error("session-unavailable");
  };
  const requireCurrentGeneration = (startedGeneration: number) => {
    if (generation !== startedGeneration) throw new TerminalSessionError();
  };
  const request = async (url: string, body: unknown, startedGeneration: number): Promise<Response> => {
    const controller = new AbortController();
    activeController = controller;
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      const response = await Promise.race([
        dependencies.fetcher(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: controller.signal }),
        new Promise<Response>((_resolve, reject) => { timer = setTimeout(() => { controller.abort(); reject(new Error("session-renewal-timeout")); }, timeoutMs); }),
      ]);
      requireCurrentGeneration(startedGeneration);
      return response;
    } finally {
      if (timer !== undefined) clearTimeout(timer);
      if (activeController === controller) activeController = null;
    }
  };
  const checkedIdentity = async (): Promise<{ registration: DeviceRegistration; device: StoredDeviceSigner }> => {
    const [registration, device] = await Promise.all([dependencies.registrations.load(), dependencies.keyStore.load()]);
    if (!registration || !device || registration.deviceId !== device.deviceId) throw new TerminalSessionError();
    return { registration, device };
  };
  const renew = async (startedGeneration: number): Promise<ExtensionBinding> => {
    try {
      const { registration, device } = await checkedIdentity();
      requireCurrentGeneration(startedGeneration);
      const challengeResponse = await request(`${registration.serverOrigin}/v1/extension/session/challenge`, { device_id: registration.deviceId, client_id: clientId }, startedGeneration);
      if ((challengeResponse.status >= 400 && challengeResponse.status < 500 && challengeResponse.status !== 429)) throw new TerminalSessionError();
      if (!challengeResponse.ok) throw new Error("renewal-unavailable");
      let challengeValue: unknown;
      try { challengeValue = await challengeResponse.json(); } catch { throw new TerminalSessionError(); }
      if (!validChallenge(challengeValue, registration.deviceId, now())) throw new TerminalSessionError();
      const challengeBytes = decodeBase64Url(challengeValue.challenge);
      if (!challengeBytes) throw new TerminalSessionError();
      const signature = await device.sign(challengeBytes);
      requireCurrentGeneration(startedGeneration);
      const renewalResponse = await request(`${registration.serverOrigin}/v1/extension/session/renew`, { device_id: registration.deviceId, challenge_id: challengeValue.challenge_id, signature }, startedGeneration);
      if ((renewalResponse.status >= 400 && renewalResponse.status < 500 && renewalResponse.status !== 429)) throw new TerminalSessionError();
      if (!renewalResponse.ok) throw new Error("renewal-unavailable");
      let renewalValue: RenewResponse;
      try { renewalValue = await renewalResponse.json() as RenewResponse; } catch { throw new TerminalSessionError(); }
      const binding = bindingFromRenewal(renewalValue, registration);
      if (!binding) throw new TerminalSessionError();
      requireCurrentGeneration(startedGeneration);
      await dependencies.sessionStore.save(binding);
      requireCurrentGeneration(startedGeneration);
      return binding;
    } catch (error) {
      return error instanceof TerminalSessionError ? terminal() : retryable();
    }
  };

  return {
    async ensureFreshBinding(minRemainingMs = defaultMinRemainingMs) {
      let current: ExtensionBinding | null;
      try { current = await dependencies.sessionStore.load(); } catch { return retryable(); }
      try {
        const { registration, device } = await checkedIdentity();
        if (current && !sameIdentity(current, registration, device)) return terminal();
        if (current && isBindingFresh(current, now(), minRemainingMs)) return current;
      } catch (error) {
        return error instanceof TerminalSessionError ? terminal() : retryable();
      }
      if (!inFlight) {
        const startedGeneration = generation;
        inFlight = renew(startedGeneration).finally(() => { inFlight = null; });
      }
      return inFlight;
    },
    async unlink() {
      generation += 1;
      activeController?.abort();
      const outcomes = await Promise.allSettled([dependencies.sessionStore.clear(), dependencies.registrations.clear(), dependencies.keyStore.clear()]);
      if (outcomes.some((outcome) => outcome.status === "rejected")) throw new Error("unlink-failed");
    },
  };
}
