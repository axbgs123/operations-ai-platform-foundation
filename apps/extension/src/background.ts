import { createSessionBindingStore, type ExtensionBinding } from "./auth/storage";
import { createDeviceKeyStore } from "./auth/device-key-store";
import { createLocalDeviceRegistrationStore } from "./auth/device-registration-store";
import { createSessionManager } from "./auth/session-renewal";
import { detectSupportedPage } from "./content/page-support";
import { parseRuntimeMessage } from "./runtime/messages";
import type { CaptureContext, CaptureMode, StartSafeCaptureMessage } from "./runtime/messages";

type BrowserTab = { id?: number; windowId?: number; url?: string };
type MessageSender = { tab?: BrowserTab };
export type SupportedTab = Required<Pick<BrowserTab, "id" | "windowId" | "url">>;

type PageStatus = CaptureContext & {
  supported: boolean;
  viewport?: { width: number; height: number; devicePixelRatio: number };
  scrollY?: number;
  url?: string;
};

export interface CaptureCoordinator {
  startCapture(mode: CaptureMode, tab: SupportedTab): Promise<void>;
  cancel(reason: string): Promise<void>;
  finishCapture?(tabId: number, captureSessionId: string): void;
}

type CaptureCoordinatorDependencies = {
  getPageStatus(tabId: number): Promise<PageStatus>;
  arm(message: StartSafeCaptureMessage | { type: "ARM_FULL_PAGE_CAPTURE"; tabId: number; captureSessionId: string } & CaptureContext & { url: string; viewport: { width: number; height: number; devicePixelRatio: number }; scrollY: number }): Promise<unknown>;
  startContent(tabId: number, message: { type: "START_CAPTURE"; mode: CaptureMode; captureSessionId?: string }): Promise<unknown>;
  endFullPageCapture?(tabId: number, captureSessionId: string): Promise<unknown>;
  uuid?: () => string;
};

const isSupportedTab = (tab: BrowserTab): tab is SupportedTab =>
  Number.isSafeInteger(tab.id) && tab.id! >= 0 &&
  Number.isSafeInteger(tab.windowId) && tab.windowId! >= 0 &&
  typeof tab.url === "string" && detectSupportedPage(tab.url).supported;

const isOk = (value: unknown) => typeof value === "object" && value !== null && "ok" in value && value.ok === true;

/** The single gesture coordinator used by both the popup and chrome.commands. */
export function createCaptureCoordinator(dependencies: CaptureCoordinatorDependencies): CaptureCoordinator {
  const fullPageSessions = new Map<number, string>();
  const uuid = dependencies.uuid ?? (() => crypto.randomUUID());
  return {
    async startCapture(mode, tab) {
      if (!isSupportedTab(tab)) throw new Error("inactive-or-unsupported-tab");
      const status = await dependencies.getPageStatus(tab.id);
      if (!status.supported || !status.platform || !status.pageVersion || !status.pageSignature) {
        throw new Error("inactive-or-unsupported-tab");
      }
      if (mode === "full-page") {
        if (!status.viewport || typeof status.scrollY !== "number" || !Number.isFinite(status.scrollY) || status.url !== tab.url) {
          throw new Error("capture-context-mismatch");
        }
        const captureSessionId = uuid();
        const armed = await dependencies.arm({
          type: "ARM_FULL_PAGE_CAPTURE",
          tabId: tab.id,
          captureSessionId,
          platform: status.platform,
          pageVersion: status.pageVersion,
          pageSignature: status.pageSignature,
          url: tab.url,
          viewport: status.viewport,
          scrollY: status.scrollY,
        });
        if (!isOk(armed)) throw new Error("capture-not-armed");
        fullPageSessions.set(tab.id, captureSessionId);
        const started = await dependencies.startContent(tab.id, { type: "START_CAPTURE", mode, captureSessionId });
        if (!isOk(started)) {
          fullPageSessions.delete(tab.id);
          await dependencies.endFullPageCapture?.(tab.id, captureSessionId);
          throw new Error("capture-start-failed");
        }
        return;
      }
      const armed = await dependencies.arm({
        type: "START_SAFE_CAPTURE",
        tabId: tab.id,
        platform: status.platform,
        pageVersion: status.pageVersion,
        pageSignature: status.pageSignature,
      });
      if (!isOk(armed)) throw new Error("capture-not-armed");
      const started = await dependencies.startContent(tab.id, { type: "START_CAPTURE", mode });
      if (!isOk(started)) throw new Error("capture-start-failed");
    },
    async cancel(reason) {
      void reason;
      await Promise.all([...fullPageSessions.entries()].map(async ([tabId, captureSessionId]) => {
        fullPageSessions.delete(tabId);
        await dependencies.endFullPageCapture?.(tabId, captureSessionId);
      }));
    },
    finishCapture(tabId, captureSessionId) {
      if (fullPageSessions.get(tabId) === captureSessionId) {
        fullPageSessions.delete(tabId);
      }
    },
  };
}

export function createCommandListener(coordinator: CaptureCoordinator) {
  return async (command: string, tab?: BrowserTab): Promise<void> => {
    if (command !== "capture-full-page" || !tab || !isSupportedTab(tab)) return;
    await coordinator.startCapture("full-page", tab);
  };
}

type BackgroundDependencies = {
  queryActiveTab(): Promise<BrowserTab>;
  captureVisibleTab(windowId: number, options: { format: "png" }): Promise<string>;
  now?: () => number;
  loadBinding?(): Promise<ExtensionBinding | null>;
  clearBinding?(): Promise<void>;
  ensureSessionBinding?(): Promise<ExtensionBinding>;
  unlinkSession?(): Promise<void>;
  captureCoordinator?: CaptureCoordinator;
};

type ArmedCapture = {
  expiresAt: number;
  platform: "douyin" | "xiaohongshu";
  pageVersion: string;
  pageSignature: string;
  url: string;
};

type ArmedFullPageCapture = ArmedCapture & {
  captureSessionId: string;
  viewport: { width: number; height: number; devicePixelRatio: number };
  nextSequence: number;
  lastScrollY: number;
  lastCaptureAt: number;
  inFlight: boolean;
};

const armLifetimeMs = 30_000;
const fullPageLifetimeMs = 20_000;
const minimumSliceIntervalMs = 500;

const isActiveSupportedTab = (candidate: BrowserTab, active: BrowserTab) =>
  candidate.id !== undefined &&
  candidate.id === active.id &&
  candidate.windowId !== undefined &&
  typeof candidate.url === "string" &&
  candidate.url === active.url &&
  detectSupportedPage(candidate.url).supported;

export function createBackgroundMessageHandler(dependencies: BackgroundDependencies) {
  const armedTabs = new Map<number, ArmedCapture>();
  const armedFullPageTabs = new Map<number, ArmedFullPageCapture>();
  const now = dependencies.now ?? Date.now;

  return async (rawMessage: unknown, sender: MessageSender): Promise<unknown> => {
    const message = parseRuntimeMessage(rawMessage);
    if (!message) return { ok: false, error: "invalid-message" };

    if (message.type === "GET_SESSION_BINDING") {
      if (sender.tab) return { ok: false, error: "unsupported-message" };
      try {
        return { ok: true, binding: await dependencies.ensureSessionBinding?.() };
      } catch {
        return { ok: false, error: "rebind-required" };
      }
    }

    if (message.type === "UNLINK_SESSION") {
      if (sender.tab) return { ok: false, error: "unsupported-message" };
      await dependencies.unlinkSession?.();
      return { ok: true };
    }

    if (message.type === "START_CAPTURE") {
      if (sender.tab || !dependencies.captureCoordinator) return { ok: false, error: "unsupported-message" };
      const active = await dependencies.queryActiveTab();
      if (!isSupportedTab(active)) return { ok: false, error: "inactive-or-unsupported-tab" };
      await dependencies.captureCoordinator.startCapture(message.mode, active);
      return { ok: true };
    }

    if (message.type === "START_SAFE_CAPTURE" && "tabId" in message) {
      const active = await dependencies.queryActiveTab();
      const detected = typeof active.url === "string" ? detectSupportedPage(active.url) : null;
      if (
        active.id !== message.tabId ||
        !isActiveSupportedTab(active, active) ||
        !detected ||
        detected.platform !== message.platform ||
        detected.pageVersion !== message.pageVersion
      ) {
        return { ok: false, error: "inactive-or-unsupported-tab" };
      }
      armedTabs.set(message.tabId, {
        expiresAt: now() + armLifetimeMs,
        platform: message.platform,
        pageVersion: message.pageVersion,
        pageSignature: message.pageSignature,
        url: active.url!,
      });
      return { ok: true };
    }

    if (message.type === "ARM_FULL_PAGE_CAPTURE") {
      const active = await dependencies.queryActiveTab();
      const detected = typeof active.url === "string" ? detectSupportedPage(active.url) : null;
      if (
        active.id !== message.tabId ||
        !isActiveSupportedTab(active, active) ||
        !detected ||
        detected.platform !== message.platform ||
        detected.pageVersion !== message.pageVersion ||
        active.url !== message.url
      ) {
        return { ok: false, error: "inactive-or-unsupported-tab" };
      }
      armedFullPageTabs.set(message.tabId, {
        expiresAt: now() + fullPageLifetimeMs,
        captureSessionId: message.captureSessionId,
        platform: message.platform,
        pageVersion: message.pageVersion,
        pageSignature: message.pageSignature,
        url: message.url,
        viewport: message.viewport,
        nextSequence: 0,
        lastScrollY: message.scrollY,
        lastCaptureAt: Number.NEGATIVE_INFINITY,
        inFlight: false,
      });
      return { ok: true };
    }

    if (message.type === "END_FULL_PAGE_CAPTURE") {
      const tab = sender.tab;
      if (!tab) return { ok: false, error: "inactive-or-unsupported-tab" };
      const armed = armedFullPageTabs.get(tab.id!);
      if (!armed || armed.captureSessionId !== message.captureSessionId) return { ok: false, error: "capture-session-mismatch" };
      armedFullPageTabs.delete(tab.id!);
      dependencies.captureCoordinator?.finishCapture?.(tab.id!, message.captureSessionId);
      return { ok: true };
    }

    if (message.type === "CAPTURE_FULL_PAGE_SLICE") {
      const tab = sender.tab;
      if (!tab) return { ok: false, error: "inactive-or-unsupported-tab" };
      const active = await dependencies.queryActiveTab();
      if (!isActiveSupportedTab(tab, active)) {
        if (tab.id !== undefined) armedFullPageTabs.delete(tab.id);
        return { ok: false, error: "inactive-or-unsupported-tab" };
      }
      const armed = armedFullPageTabs.get(tab.id!);
      if (!armed || armed.expiresAt <= now()) {
        if (tab.id !== undefined) armedFullPageTabs.delete(tab.id);
        return { ok: false, error: "capture-not-armed" };
      }
      if (armed.captureSessionId !== message.captureSessionId) return { ok: false, error: "capture-session-mismatch" };
      if (armed.nextSequence !== message.sequence) return { ok: false, error: "capture-sequence-mismatch" };
      const detected = detectSupportedPage(tab.url!);
      if (
        armed.platform !== message.platform || armed.pageVersion !== message.pageVersion ||
        armed.pageSignature !== message.pageSignature || armed.url !== message.url || tab.url !== message.url ||
        armed.viewport.width !== message.viewport.width || armed.viewport.height !== message.viewport.height ||
        armed.viewport.devicePixelRatio !== message.viewport.devicePixelRatio || message.scrollY < armed.lastScrollY ||
        (message.sequence === 0 && message.scrollY !== armed.lastScrollY) ||
        !detected || detected.platform !== armed.platform || detected.pageVersion !== armed.pageVersion
      ) {
        armedFullPageTabs.delete(tab.id!);
        return { ok: false, error: "capture-context-mismatch" };
      }
      if (armed.inFlight) return { ok: false, error: "capture-in-progress" };
      if (now() - armed.lastCaptureAt < minimumSliceIntervalMs) return { ok: false, error: "capture-rate-limit" };
      armed.inFlight = true;
      let dataUrl: string;
      try {
        dataUrl = await dependencies.captureVisibleTab(tab.windowId!, { format: "png" });
      } catch {
        if (armedFullPageTabs.get(tab.id!) === armed) {
          armedFullPageTabs.delete(tab.id!);
          return { ok: false, error: "capture-failed" };
        }
        return { ok: false, error: "capture-not-armed" };
      } finally {
        if (armedFullPageTabs.get(tab.id!) === armed) armed.inFlight = false;
      }
      if (armedFullPageTabs.get(tab.id!) !== armed) {
        return { ok: false, error: "capture-not-armed" };
      }
      if (armed.expiresAt <= now()) {
        armedFullPageTabs.delete(tab.id!);
        return { ok: false, error: "capture-not-armed" };
      }
      armed.nextSequence += 1;
      armed.lastScrollY = message.scrollY;
      armed.lastCaptureAt = now();
      return { ok: true, dataUrl };
    }

    if (message.type === "GET_CAPTURE_BINDING") {
      const tab = sender.tab;
      if (!tab) return { ok: false, error: "inactive-or-unsupported-tab" };
      const active = await dependencies.queryActiveTab();
      if (!isActiveSupportedTab(tab, active)) {
        return { ok: false, error: "inactive-or-unsupported-tab" };
      }
      const armed = armedTabs.get(tab.id!);
      const fullPageArmed = armedFullPageTabs.get(tab.id!);
      const activeArm = armed ?? fullPageArmed;
      if (!activeArm || activeArm.expiresAt <= now()) {
        return { ok: false, error: "capture-not-armed" };
      }
      if (
        activeArm.platform !== message.platform ||
        activeArm.pageVersion !== message.pageVersion ||
        activeArm.pageSignature !== message.pageSignature ||
        activeArm.url !== tab.url
      ) {
        return { ok: false, error: "capture-context-mismatch" };
      }
      const binding = await dependencies.loadBinding?.();
      if (!binding || Date.parse(binding.expiresAt) <= now()) {
        await dependencies.clearBinding?.();
        return { ok: false, error: "rebind-required" };
      }
      return {
        ok: true,
        binding: {
          serverOrigin: binding.serverOrigin,
          webOrigin: binding.webOrigin,
          workspaceId: binding.workspaceId,
          accessToken: binding.accessToken,
          expiresAt: binding.expiresAt,
          providerMode: binding.providerMode,
        },
      };
    }

    if (message.type === "CLEAR_CAPTURE_BINDING") {
      const tab = sender.tab;
      if (!tab) return { ok: false, error: "inactive-or-unsupported-tab" };
      const active = await dependencies.queryActiveTab();
      const detected = typeof tab.url === "string" ? detectSupportedPage(tab.url) : null;
      if (
        !isActiveSupportedTab(tab, active) ||
        !detected ||
        detected.platform !== message.platform ||
        detected.pageVersion !== message.pageVersion
      ) {
        return { ok: false, error: "inactive-or-unsupported-tab" };
      }
      await dependencies.clearBinding?.();
      return { ok: true };
    }

    if (message.type === "CAPTURE_VISIBLE_TAB") {
      const tab = sender.tab;
      if (!tab) return { ok: false, error: "inactive-or-unsupported-tab" };
      const active = await dependencies.queryActiveTab();
      if (!isActiveSupportedTab(tab, active)) {
        if (tab.id !== undefined) armedTabs.delete(tab.id);
        return { ok: false, error: "inactive-or-unsupported-tab" };
      }
      const armed = armedTabs.get(tab.id!);
      armedTabs.delete(tab.id!);
      if (armed === undefined || armed.expiresAt <= now()) {
        return { ok: false, error: "capture-not-armed" };
      }
      const detected = detectSupportedPage(tab.url!);
      if (
        armed.platform !== detected.platform ||
        armed.pageVersion !== detected.pageVersion ||
        armed.pageSignature !== message.pageSignature ||
        armed.url !== tab.url
      ) {
        return { ok: false, error: "capture-context-mismatch" };
      }
      const dataUrl = await dependencies.captureVisibleTab(tab.windowId!, { format: "png" });
      return { ok: true, dataUrl };
    }

    return { ok: false, error: "unsupported-message" };
  };
}

declare const chrome: {
  storage: {
    session: {
      get(key: string): Promise<Record<string, unknown>>;
      set(values: Record<string, unknown>): Promise<void>;
      remove(key: string): Promise<void>;
    };
    local: {
      get(key: string): Promise<Record<string, unknown>>;
      set(values: Record<string, unknown>): Promise<void>;
      remove(key: string): Promise<void>;
    };
  };
  runtime: {
    onMessage: {
      addListener(
        listener: (
          message: unknown,
          sender: MessageSender,
          sendResponse: (response: unknown) => void,
        ) => boolean | void,
      ): void;
    };
  };
  commands: {
    onCommand: { addListener(listener: (command: string, tab?: BrowserTab) => void): void };
  };
  tabs: {
    query(options: { active: boolean; currentWindow: boolean }): Promise<BrowserTab[]>;
    captureVisibleTab(windowId: number, options: { format: "png" }): Promise<string>;
    sendMessage(tabId: number, message: unknown): Promise<unknown>;
  };
};

if (typeof chrome !== "undefined") {
  const bindingStore = createSessionBindingStore(chrome.storage.session);
  const sessionManager = createSessionManager({
    keyStore: createDeviceKeyStore(),
    registrations: createLocalDeviceRegistrationStore(chrome.storage.local),
    sessionStore: bindingStore,
    fetcher: fetch,
  });
  let handler: ReturnType<typeof createBackgroundMessageHandler>;
  const coordinator = createCaptureCoordinator({
    getPageStatus: async (tabId) => chrome.tabs.sendMessage(tabId, { type: "GET_PAGE_STATUS" }) as Promise<PageStatus>,
    arm: (message) => handler(message, {}),
    startContent: (tabId, message) => chrome.tabs.sendMessage(tabId, message),
    endFullPageCapture: (tabId, captureSessionId) => handler(
      { type: "END_FULL_PAGE_CAPTURE", captureSessionId },
      { tab: { id: tabId } },
    ),
  });
  handler = createBackgroundMessageHandler({
    queryActiveTab: async () =>
      (await chrome.tabs.query({ active: true, currentWindow: true }))[0] ?? {},
    captureVisibleTab: (windowId, options) => chrome.tabs.captureVisibleTab(windowId, options),
    loadBinding: () => sessionManager.ensureFreshBinding().catch(() => null),
    clearBinding: () => sessionManager.unlink(),
    ensureSessionBinding: () => sessionManager.ensureFreshBinding(),
    unlinkSession: () => sessionManager.unlink(),
    captureCoordinator: coordinator,
  });
  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    void handler(message, sender).then(sendResponse, () =>
      sendResponse({ ok: false, error: "capture-failed" }),
    );
    return true;
  });
  chrome.commands.onCommand.addListener((command, tab) => {
    void createCommandListener(coordinator)(command, tab);
  });
}
