export type ExtensionBinding = {
  serverOrigin: string;
  accessToken: string;
  expiresAt: string;
  providerMode: string;
  region: string | null;
};

export type BindingStore = {
  load(): Promise<ExtensionBinding | null>;
  save(binding: ExtensionBinding): Promise<void>;
  clear(): Promise<void>;
};

export function createMemoryBindingStore(): BindingStore {
  let binding: ExtensionBinding | null = null;
  return {
    async load() {
      return binding;
    },
    async save(next) {
      binding = { ...next };
    },
    async clear() {
      binding = null;
    },
  };
}

type SessionStorageArea = {
  get(key: string): Promise<Record<string, unknown>>;
  set(values: Record<string, unknown>): Promise<void>;
  remove(key: string): Promise<void>;
};

const storageKey = "extensionBinding";

export function createSessionBindingStore(
  session: SessionStorageArea,
): BindingStore {
  return {
    async load() {
      const result = await session.get(storageKey);
      return (result[storageKey] as ExtensionBinding | undefined) ?? null;
    },
    async save(binding) {
      await session.set({ [storageKey]: binding });
    },
    async clear() {
      await session.remove(storageKey);
    },
  };
}
