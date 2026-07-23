export type TrustContext = {
  serverOrigin: string;
  platform: "douyin" | "xiaohongshu";
  pageSignature: string;
  pageVersion: string;
  extensionVersion: string;
  captureRegionFingerprint: string;
  sensitiveRegionFingerprint: string;
};

export type TrustRecord = TrustContext & {
  trustedAt: string;
};

export type TrustStorage = {
  load(): Promise<TrustRecord | null>;
  save(record: TrustRecord): Promise<void>;
  clear(): Promise<void>;
};

type MetadataStorage = {
  get(key: string): Promise<Record<string, unknown>>;
  set(values: Record<string, unknown>): Promise<void>;
  remove(key: string): Promise<void>;
};

const trustKey = "captureTrustState";

export function createTrustStore(): TrustStorage {
  let record: TrustRecord | null = null;
  return {
    async load() {
      return record ? { ...record } : null;
    },
    async save(next) {
      record = { ...next };
    },
    async clear() {
      record = null;
    },
  };
}

function isTrustRecord(value: unknown): value is TrustRecord {
  if (!value || typeof value !== "object") return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.serverOrigin === "string" &&
    (record.platform === "douyin" || record.platform === "xiaohongshu") &&
    typeof record.pageSignature === "string" &&
    typeof record.pageVersion === "string" &&
    typeof record.extensionVersion === "string" &&
    typeof record.captureRegionFingerprint === "string" &&
    typeof record.sensitiveRegionFingerprint === "string" &&
    typeof record.trustedAt === "string"
  );
}

export function createPersistedTrustStore(storage: MetadataStorage): TrustStorage {
  return {
    async load() {
      const value = (await storage.get(trustKey))[trustKey];
      return isTrustRecord(value) ? { ...value } : null;
    },
    async save(record) {
      await storage.set({ [trustKey]: { ...record } });
    },
    async clear() {
      await storage.remove(trustKey);
    },
  };
}

export async function establishTrust(
  store: TrustStorage,
  context: TrustContext,
  options: { safeCaptureCompleted: boolean } = { safeCaptureCompleted: true },
): Promise<TrustRecord> {
  if (!options.safeCaptureCompleted) throw new Error("safe-capture-required");
  const record: TrustRecord = {
    ...context,
    trustedAt: new Date().toISOString(),
  };
  await store.save(record);
  return record;
}

export function trustMatches(
  record: TrustRecord,
  context: TrustContext,
): boolean {
  return (
    record.serverOrigin === context.serverOrigin &&
    record.platform === context.platform &&
    record.pageSignature === context.pageSignature &&
    record.pageVersion === context.pageVersion &&
    record.extensionVersion === context.extensionVersion &&
    record.captureRegionFingerprint === context.captureRegionFingerprint &&
    record.sensitiveRegionFingerprint === context.sensitiveRegionFingerprint
  );
}
