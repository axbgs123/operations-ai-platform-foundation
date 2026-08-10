import { pairExtension, revokeExtension, type PairingInput } from "../auth/client";
import { createDeviceKeyStore } from "../auth/device-key-store";
import { createLocalDeviceRegistrationStore } from "../auth/device-registration-store";
import { createSessionManager } from "../auth/session-renewal";
import { createSessionBindingStore, type BindingStore, type ExtensionBinding } from "../auth/storage";
import { extensionVersion } from "../build-metadata";
import { createPersistedTrustStore } from "../capture/trust-state";
import { detectSupportedPage } from "../content/page-support";
import type { CaptureContext, StartSafeCaptureMessage } from "../runtime/messages";

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
  permissions: {
    contains(options: { origins: string[] }): Promise<boolean>;
    request(options: { origins: string[] }): Promise<boolean>;
  };
  tabs: {
    query(options: { active: boolean; currentWindow: boolean }): Promise<Array<{ id?: number; url?: string }>>;
    sendMessage(tabId: number, message: { type: "GET_PAGE_STATUS" }): Promise<PageStatus>;
    sendMessage(tabId: number, message: { type: "START_SAFE_CAPTURE" }): Promise<unknown>;
  };
  runtime: {
    sendMessage(message: StartSafeCaptureMessage): Promise<unknown>;
  };
};

const defaultServerOrigin = "http://127.0.0.1:51201";

export type PageStatus = {
  supported: boolean;
  platform: "douyin" | "xiaohongshu" | null;
  pageVersion: string;
  pageSignature: string;
  reason?: string;
};

export type PopupMessage =
  | { type: "GET_PAGE_STATUS" }
  | { type: "START_SAFE_CAPTURE" };

export type PopupDependencies = {
  store: BindingStore;
  pair(input: PairingInput): Promise<unknown>;
  revoke(): Promise<void>;
  getPageStatus(): Promise<PageStatus>;
  startSafeCapture(message: Extract<PopupMessage, { type: "START_SAFE_CAPTURE" }>): Promise<unknown>;
  ensureFreshBinding?(): Promise<ExtensionBinding>;
  now?(): number;
  onUnbound?(): Promise<void>;
};

type PopupElements = {
  form: HTMLFormElement | null;
  pairingCode: HTMLInputElement | null;
  advancedToggle: HTMLButtonElement | null;
  advancedSettings: HTMLElement | null;
  serverOrigin: HTMLInputElement | null;
  destination: HTMLElement | null;
  member: HTMLElement | null;
  processing: HTMLElement | null;
  expiry: HTMLElement | null;
  pageStatus: HTMLElement | null;
  status: HTMLElement | null;
  start: HTMLButtonElement | null;
  unbind: HTMLButtonElement | null;
};

const processingText = (binding: ExtensionBinding) =>
  binding.providerMode === "mock"
    ? "处理方式：Mock（不会调用外部付费模型）"
    : binding.providerMode === "qianwen"
      ? `处理方式：阿里云百炼 Qwen-OCR · 地域 ${binding.region ?? "未配置"} · 会产生模型调用费用`
      : "处理方式：当前不可用，请在 Web 端检查设置。";

const unsupportedPage = (): PageStatus => ({
  supported: false,
  platform: null,
  pageVersion: "unknown",
  pageSignature: "unsupported",
  reason: "unsupported-url",
});

export function createPopupController(
  root: Document,
  dependencies: PopupDependencies,
) {
  const elements: PopupElements = {
    form: root.querySelector("#pairing-form"),
    pairingCode: root.querySelector("#pairing-code"),
    advancedToggle: root.querySelector("#advanced-toggle"),
    advancedSettings: root.querySelector("#advanced-settings"),
    serverOrigin: root.querySelector("#server-origin"),
    destination: root.querySelector("#destination"),
    member: root.querySelector("#member"),
    processing: root.querySelector("#processing"),
    expiry: root.querySelector("#expiry"),
    pageStatus: root.querySelector("#page-status"),
    status: root.querySelector("#status"),
    start: root.querySelector("#start-safe-capture"),
    unbind: root.querySelector("#unbind"),
  };
  const now = dependencies.now ?? Date.now;
  let currentStatus = unsupportedPage();
  let currentBinding: ExtensionBinding | null = null;

  if (elements.serverOrigin) elements.serverOrigin.value = defaultServerOrigin;

  const renderUnpaired = (message = "请输入 Web 端生成的连接码。") => {
    currentBinding = null;
    currentStatus = unsupportedPage();
    if (elements.form) elements.form.hidden = false;
    if (elements.advancedToggle) elements.advancedToggle.hidden = false;
    if (elements.advancedSettings) elements.advancedSettings.hidden = true;
    if (elements.destination) elements.destination.textContent = "采集将发送至：尚未连接";
    if (elements.member) elements.member.textContent = "";
    if (elements.processing) elements.processing.textContent = "处理方式：连接后由服务器提供";
    if (elements.expiry) elements.expiry.textContent = "";
    if (elements.pageStatus) elements.pageStatus.textContent = "请先连接工作区。";
    if (elements.status) elements.status.textContent = message;
    if (elements.start) elements.start.hidden = true;
    if (elements.unbind) elements.unbind.hidden = true;
  };

  const renderPaired = (binding: ExtensionBinding, pageStatus: PageStatus) => {
    currentBinding = binding;
    currentStatus = pageStatus;
    if (elements.form) elements.form.hidden = true;
    if (elements.advancedToggle) elements.advancedToggle.hidden = true;
    if (elements.advancedSettings) elements.advancedSettings.hidden = true;
    if (elements.destination) elements.destination.textContent = `采集将发送至：${binding.webOrigin} · ${binding.workspaceName}`;
    if (elements.member) elements.member.textContent = `已连接成员：${binding.memberDisplayName}`;
    if (elements.processing) elements.processing.textContent = processingText(binding);
    if (elements.expiry) elements.expiry.textContent = `连接有效至：${new Date(binding.expiresAt).toLocaleString("zh-CN")}`;
    if (elements.pageStatus) {
      elements.pageStatus.textContent = pageStatus.supported
        ? `当前页面已就绪：${pageStatus.platform === "douyin" ? "抖音创作者中心" : "小红书创作中心"}`
        : "当前页面暂不支持。请打开抖音或小红书的内容管理页后重试。";
    }
    if (elements.status) elements.status.textContent = pageStatus.supported ? "可以开始安全采集。" : "已连接，等待受支持页面。";
    if (elements.start) elements.start.hidden = !pageStatus.supported;
    if (elements.unbind) elements.unbind.hidden = false;
  };

  const render = async (): Promise<void> => {
    let binding: ExtensionBinding | null;
    try {
      binding = dependencies.ensureFreshBinding
        ? await dependencies.ensureFreshBinding()
        : await dependencies.store.load();
    } catch {
      return renderUnpaired("连接已失效，请重新输入连接码。");
    }
    if (!binding) return renderUnpaired();
    if (Date.parse(binding.expiresAt) <= now()) {
      await dependencies.store.clear();
      return renderUnpaired("连接已过期，请重新输入连接码。");
    }
    let pageStatus: PageStatus;
    try {
      pageStatus = await dependencies.getPageStatus();
    } catch {
      pageStatus = unsupportedPage();
    }
    renderPaired(binding, pageStatus);
  };

  const submit = async (): Promise<void> => {
    const pairingCode = elements.pairingCode?.value ?? "";
    const serverOrigin = elements.serverOrigin?.value || defaultServerOrigin;
    try {
      await dependencies.pair({
        serverOrigin,
        pairingCode,
        clientId: "operations-capture-extension",
      });
      await render();
    } catch (error) {
      if (elements.status) {
        elements.status.textContent = error instanceof Error ? error.message : "服务器配对失败";
      }
    } finally {
      if (elements.pairingCode) elements.pairingCode.value = "";
    }
  };

  const start = async (): Promise<void> => {
    if (!currentBinding || !currentStatus.supported) return;
    await dependencies.startSafeCapture({ type: "START_SAFE_CAPTURE" });
  };

  const unbind = async (): Promise<void> => {
    let remoteRevocationFailed = false;
    try {
      await dependencies.revoke();
    } catch {
      remoteRevocationFailed = true;
    } finally {
      try {
        await dependencies.onUnbound?.();
      } catch {
        // The visible state must still fail closed if local trust cleanup errors.
      }
      await render();
    }
    if (remoteRevocationFailed && elements.status) {
      elements.status.textContent = "本地已解绑，但未能通知服务器；服务端令牌将在到期后自动失效。";
    }
  };

  elements.form?.addEventListener("submit", (event) => {
    event.preventDefault();
    void submit();
  });
  elements.advancedToggle?.addEventListener("click", () => {
    if (elements.advancedSettings) elements.advancedSettings.hidden = !elements.advancedSettings.hidden;
  });
  elements.start?.addEventListener("click", () => void start());
  elements.unbind?.addEventListener("click", () => void unbind());

  return { render, submit, start, unbind };
}

async function activeTab(): Promise<{ id?: number; url?: string }> {
  return (await chrome.tabs.query({ active: true, currentWindow: true }))[0] ?? {};
}

async function getChromePageStatus(): Promise<PageStatus> {
  const tab = await activeTab();
  if (tab.id !== undefined) {
    try {
      return await chrome.tabs.sendMessage(tab.id, { type: "GET_PAGE_STATUS" });
    } catch {
      // A content script may not yet be ready; URL-only detection remains safe.
    }
  }
  const page = tab.url ? detectSupportedPage(tab.url) : unsupportedPage();
  return {
    supported: false,
    platform: page.platform,
    pageVersion: page.pageVersion,
    pageSignature: "unavailable",
    reason: "content-script-unavailable",
  };
}

async function startChromeSafeCapture(message: Extract<PopupMessage, { type: "START_SAFE_CAPTURE" }>): Promise<void> {
  const tab = await activeTab();
  if (tab.id === undefined) throw new Error("未找到当前页面");
  const status = await chrome.tabs.sendMessage(tab.id, { type: "GET_PAGE_STATUS" });
  if (!status.supported || !status.platform || !status.pageSignature) {
    throw new Error("当前页面尚未准备好安全采集");
  }
  await armAndStartSafeCapture(
    tab.id,
    {
      platform: status.platform,
      pageVersion: status.pageVersion,
      pageSignature: status.pageSignature,
    },
    (armMessage) => chrome.runtime.sendMessage(armMessage),
    (contentMessage) => chrome.tabs.sendMessage(tab.id!, contentMessage),
  );
}

export async function armAndStartSafeCapture(
  tabId: number,
  context: CaptureContext,
  arm: (message: StartSafeCaptureMessage) => Promise<unknown>,
  startContent: (message: StartSafeCaptureMessage) => Promise<unknown>,
): Promise<void> {
  const response = await arm({ type: "START_SAFE_CAPTURE", tabId, ...context });
  if (
    typeof response !== "object" ||
    response === null ||
    !("ok" in response) ||
    response.ok !== true
  ) {
    throw new Error("capture-not-armed");
  }
  const startResponse = await startContent({ type: "START_SAFE_CAPTURE" });
  if (
    typeof startResponse !== "object" ||
    startResponse === null ||
    !("ok" in startResponse) ||
    startResponse.ok !== true
  ) {
    const error =
      typeof startResponse === "object" &&
      startResponse !== null &&
      "error" in startResponse &&
      typeof startResponse.error === "string"
        ? startResponse.error
        : "capture-start-failed";
    throw new Error(error);
  }
}

if (typeof chrome !== "undefined") {
  const store = createSessionBindingStore(chrome.storage.session);
  const keyStore = createDeviceKeyStore();
  const registrations = createLocalDeviceRegistrationStore(chrome.storage.local);
  const sessionManager = createSessionManager({
    keyStore,
    registrations,
    sessionStore: store,
    fetcher: fetch,
  });
  const trustStore = createPersistedTrustStore(chrome.storage.local);
  const controller = createPopupController(document, {
    store,
    pair: (input) =>
      pairExtension({ ...input, deviceLabel: "Chrome extension", extensionVersion }, {
        fetcher: fetch,
        store,
        keyStore,
        registrations,
        clearPairingCode: () => undefined,
        hasOriginPermission: (originPattern) => chrome.permissions.contains({ origins: [originPattern] }),
        requestOriginPermission: (originPattern) => chrome.permissions.request({ origins: [originPattern] }),
      }),
    revoke: () => revokeExtension(store, fetch),
    ensureFreshBinding: () => sessionManager.ensureFreshBinding(),
    getPageStatus: getChromePageStatus,
    startSafeCapture: startChromeSafeCapture,
    onUnbound: async () => {
      await sessionManager.unlink();
      await trustStore.clear();
    },
  });
  void controller.render();
}
