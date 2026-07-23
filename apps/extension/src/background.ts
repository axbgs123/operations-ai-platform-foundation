import { createSessionBindingStore } from "./auth/storage";

declare const chrome: {
  storage: {
    session: {
      get(key: string): Promise<Record<string, unknown>>;
      set(values: Record<string, unknown>): Promise<void>;
      remove(key: string): Promise<void>;
    };
  };
  runtime: {
    onMessage: {
      addListener(
        listener: (
          message: { type?: string },
          sender: unknown,
          sendResponse: (response: unknown) => void,
        ) => boolean | void,
      ): void;
    };
  };
};

chrome.runtime.onMessage.addListener((_message, _sender, sendResponse) => {
  const store = createSessionBindingStore(chrome.storage.session);
  void store.load().then(async (binding) => {
    if (binding && Date.parse(binding.expiresAt) <= Date.now()) {
      await store.clear();
      sendResponse({ bound: false, reason: "expired" });
      return;
    }
    sendResponse({
      bound: binding !== null,
      serverOrigin: binding?.serverOrigin,
      expiresAt: binding?.expiresAt,
    });
  });
  return true;
});
