import { detectSupportedPage } from "./content/page-support";
import { parseRuntimeMessage } from "./runtime/messages";

type BrowserTab = { id?: number; windowId?: number; url?: string };
type MessageSender = { tab?: BrowserTab };

type BackgroundDependencies = {
  queryActiveTab(): Promise<BrowserTab>;
  captureVisibleTab(windowId: number, options: { format: "png" }): Promise<string>;
  now?: () => number;
};

type ArmedCapture = {
  expiresAt: number;
  platform: "douyin" | "xiaohongshu";
  pageVersion: string;
  pageSignature: string;
  url: string;
};

const armLifetimeMs = 30_000;

const isActiveSupportedTab = (candidate: BrowserTab, active: BrowserTab) =>
  candidate.id !== undefined &&
  candidate.id === active.id &&
  candidate.windowId !== undefined &&
  typeof candidate.url === "string" &&
  candidate.url === active.url &&
  detectSupportedPage(candidate.url).supported;

export function createBackgroundMessageHandler(dependencies: BackgroundDependencies) {
  const armedTabs = new Map<number, ArmedCapture>();
  const now = dependencies.now ?? Date.now;

  return async (rawMessage: unknown, sender: MessageSender): Promise<unknown> => {
    const message = parseRuntimeMessage(rawMessage);
    if (!message) return { ok: false, error: "invalid-message" };

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
  tabs: {
    query(options: { active: boolean; currentWindow: boolean }): Promise<BrowserTab[]>;
    captureVisibleTab(windowId: number, options: { format: "png" }): Promise<string>;
  };
};

if (typeof chrome !== "undefined") {
  const handler = createBackgroundMessageHandler({
    queryActiveTab: async () =>
      (await chrome.tabs.query({ active: true, currentWindow: true }))[0] ?? {},
    captureVisibleTab: (windowId, options) => chrome.tabs.captureVisibleTab(windowId, options),
  });
  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    void handler(message, sender).then(sendResponse, () =>
      sendResponse({ ok: false, error: "capture-failed" }),
    );
    return true;
  });
}
