import { bindExtension, revokeExtension } from "../auth/client";
import { createSessionBindingStore } from "../auth/storage";
import { createPersistedTrustStore } from "../capture/trust-state";

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
    request(options: { origins: string[] }): Promise<boolean>;
  };
};

const store = createSessionBindingStore(chrome.storage.session);
const trustStore = createPersistedTrustStore(chrome.storage.local);
const form = document.querySelector<HTMLFormElement>("#binding-form");
const serverInput =
  document.querySelector<HTMLInputElement>("#server-origin");
const inviteInput = document.querySelector<HTMLInputElement>("#invite-code");
const status = document.querySelector<HTMLElement>("#status");
const destination = document.querySelector<HTMLElement>("#destination");
const unbind = document.querySelector<HTMLButtonElement>("#unbind");
const trustPanel = document.querySelector<HTMLElement>("#trust-panel");
const trustDetails = document.querySelector<HTMLElement>("#trust-details");
const disableOneClick = document.querySelector<HTMLButtonElement>("#disable-one-click");

async function render(): Promise<void> {
  const binding = await store.load();
  if (binding && Date.parse(binding.expiresAt) > Date.now()) {
    if (destination) destination.textContent = `截图将上传到：${binding.serverOrigin}`;
    if (status) {
      const minutes = Math.max(
        0,
        Math.ceil((Date.parse(binding.expiresAt) - Date.now()) / 60_000),
      );
      status.textContent = `已绑定，令牌约 ${minutes} 分钟后过期。`;
    }
    const trust = await trustStore.load();
    if (trustPanel && trustDetails && trust) {
      trustPanel.hidden = false;
      trustDetails.textContent = `${trust.serverOrigin} · ${trust.platform} · ${trust.pageVersion} · 信任于 ${trust.trustedAt}`;
    }
    return;
  }
  if (binding) await store.clear();
  if (destination) destination.textContent = "截图将上传到：尚未绑定";
  if (status) status.textContent = "需要重新绑定。";
  if (trustPanel) trustPanel.hidden = true;
}

form?.addEventListener("submit", (event) => {
  event.preventDefault();
  const serverOrigin = serverInput?.value ?? "";
  const inviteCode = inviteInput?.value ?? "";
  void bindExtension(
    {
      serverOrigin,
      inviteCode,
      clientId: "operations-capture-extension",
    },
    {
      fetcher: fetch,
      store,
      clearInvite: () => {
        if (inviteInput) inviteInput.value = "";
      },
      requestOriginPermission: (originPattern) =>
        chrome.permissions.request({ origins: [originPattern] }),
    },
  )
    .then(render)
    .catch((error: unknown) => {
      if (status) {
        status.textContent =
          error instanceof Error ? error.message : "服务器绑定失败";
      }
    });
});

unbind?.addEventListener("click", () => {
  void revokeExtension(store, fetch).then(async () => {
    await trustStore.clear();
    await render();
  });
});

disableOneClick?.addEventListener("click", () => {
  void trustStore.clear().then(render);
});

void render();
