import { createSessionBindingStore, type ExtensionBinding } from "./auth/storage";
import { pollCaptureTask, type CaptureTaskRead } from "./capture/task-status";
import { uploadPreview } from "./capture/upload";
import { CaptureOverlay } from "./content/capture-overlay";
import { applyRedactions, cropVisibleTab } from "./content/image-processing";
import { CaptureState } from "./content/overlay";
import { detectPage, type PageDetection } from "./content/page-adapters/base";
import { parseRuntimeMessage } from "./runtime/messages";

type ContentDependencies = {
  detect(): PageDetection;
  startCapture(): Promise<void>;
};

export function createContentMessageHandler(dependencies: ContentDependencies) {
  return async (rawMessage: unknown): Promise<unknown> => {
    const message = parseRuntimeMessage(rawMessage);
    if (!message) return { ok: false, error: "invalid-message" };
    if (message.type === "GET_PAGE_STATUS") {
      const result = dependencies.detect();
      return {
        supported: result.supported,
        platform: result.platform,
        pageVersion: result.pageVersion,
        pageSignature: result.signature,
      };
    }
    if (message.type === "START_SAFE_CAPTURE" && !("tabId" in message)) {
      await dependencies.startCapture();
      return { ok: true };
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
  };
  runtime: {
    sendMessage(message: unknown): Promise<unknown>;
    onMessage: {
      addListener(
        listener: (
          message: unknown,
          sender: unknown,
          sendResponse: (response: unknown) => void,
        ) => boolean | void,
      ): void;
    };
  };
};

type CaptureResponse = { ok: true; dataUrl: string } | { ok: false; error: string };

const isCaptureResponse = (value: unknown): value is CaptureResponse => {
  if (typeof value !== "object" || value === null || !("ok" in value)) return false;
  if (value.ok === true) return "dataUrl" in value && typeof value.dataUrl === "string";
  return value.ok === false && "error" in value && typeof value.error === "string";
};

const currentDetection = () => detectPage({ url: window.location.href, document });

function finalPreviewController(dataUrl: string) {
  return {
    state: CaptureState.PreviewReady,
    preview: { imageData: dataUrl, maskedRegions: [] },
    canUpload: () => true,
  };
}

function mountChromeCapture(
  binding: ExtensionBinding,
  onDestroy: (overlay: CaptureOverlay) => void,
): CaptureOverlay {
  const initial = currentDetection();
  const store = createSessionBindingStore(chrome.storage.session);
  const overlay = CaptureOverlay.mount({
    document,
    viewport: {
      width: window.innerWidth,
      height: window.innerHeight,
      devicePixelRatio: window.devicePixelRatio || 1,
    },
    getViewport: () => ({
      width: window.innerWidth,
      height: window.innerHeight,
      devicePixelRatio: window.devicePixelRatio || 1,
    }),
    detect: currentDetection,
    binding,
    crop: cropVisibleTab,
    redact: applyRedactions,
    captureVisibleTab: async () => {
      const response = await chrome.runtime.sendMessage({
        type: "CAPTURE_VISIBLE_TAB",
        pageSignature: initial.signature,
      });
      if (!isCaptureResponse(response)) throw new Error("capture-failed");
      if (!response.ok) throw new Error(response.error);
      return response.dataUrl;
    },
    upload: (dataUrl, idempotencyKey) =>
      uploadPreview({
        controller: finalPreviewController(dataUrl),
        serverOrigin: binding.serverOrigin,
        accessToken: binding.accessToken,
        workspaceId: binding.workspaceId,
        platform: initial.platform!,
        pageVersion: initial.pageVersion,
        pageIdentifier: initial.signature,
        collectedAt: new Date().toISOString(),
        idempotencyKey,
        onRebindRequired: () => store.clear(),
      }),
    poll: (task: CaptureTaskRead) =>
      pollCaptureTask({
        serverOrigin: binding.serverOrigin,
        accessToken: binding.accessToken,
        taskId: task.task_id,
        platform: initial.platform!,
        pageVersion: initial.pageVersion,
        onRebindRequired: () => store.clear(),
      }),
    onRePairRequired: () => store.clear(),
    onDestroy,
  });
  return overlay;
}

if (typeof window !== "undefined" && typeof document !== "undefined" && typeof chrome !== "undefined") {
  let activeOverlay: CaptureOverlay | null = null;
  const detection = currentDetection();
  document.documentElement.dataset.operationsCaptureSupported = String(detection.supported);
  document.documentElement.dataset.operationsCapturePlatform = detection.platform ?? "unknown";
  document.documentElement.dataset.operationsCaptureSignature = detection.signature;
  const store = createSessionBindingStore(chrome.storage.session);
  const handler = createContentMessageHandler({
    detect: currentDetection,
    startCapture: async () => {
      const binding = await store.load();
      if (!binding || Date.parse(binding.expiresAt) <= Date.now()) {
        await store.clear();
        throw new Error("rebind-required");
      }
      activeOverlay?.cancel();
      activeOverlay = mountChromeCapture(binding, (overlay) => {
        if (activeOverlay === overlay) activeOverlay = null;
      });
    },
  });
  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    void handler(message).then(sendResponse, (error) =>
      sendResponse({
        ok: false,
        error: error instanceof Error ? error.message : "capture-start-failed",
      }),
    );
    return true;
  });
}
