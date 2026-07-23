type ExtensionState = {
  serverOrigin?: string;
  flow: "idle";
};

const initialState: ExtensionState = { flow: "idle" };

declare const chrome: {
  storage: {
    session: {
      get(keys: string[]): Promise<Record<string, unknown>>;
      set(values: Record<string, unknown>): Promise<void>;
    };
  };
  runtime: {
    onMessage: {
      addListener(
        listener: (
          message: { type?: string },
          sender: unknown,
          sendResponse: (response: ExtensionState) => void,
        ) => void,
      ): void;
    };
  };
};

chrome.runtime.onMessage.addListener((_message, _sender, sendResponse) => {
  void chrome.storage.session.get(["extensionState"]).then((stored) => {
    sendResponse(
      (stored.extensionState as ExtensionState | undefined) ?? initialState,
    );
  });
});
