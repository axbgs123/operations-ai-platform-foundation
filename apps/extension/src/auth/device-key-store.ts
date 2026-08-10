export type DeviceSigner = {
  deviceId: string;
  publicJwk: JsonWebKey;
  sign(payload: Uint8Array): Promise<string>;
};

export type StoredDeviceSigner = DeviceSigner & {
  privateKey: CryptoKey;
};

export type DeviceKeyStore = {
  getOrCreate(): Promise<StoredDeviceSigner>;
  load(): Promise<StoredDeviceSigner | null>;
  clear(): Promise<void>;
};

export type DeviceKeyRecord = {
  id: "device";
  deviceId: string;
  publicJwk: JsonWebKey;
  privateKey: CryptoKey;
};

const databaseName = "operations-ai-extension-device";
const storeName = "device-keys";
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const publicKeyFields = ["crv", "kty", "x", "y"];

function encodeBase64Url(value: ArrayBuffer): string {
  const bytes = new Uint8Array(value);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function normalizePublicJwk(value: JsonWebKey): JsonWebKey | null {
  if (value.kty !== "EC" || value.crv !== "P-256" ||
    typeof value.x !== "string" || !/^[A-Za-z0-9_-]{43}$/.test(value.x) ||
    typeof value.y !== "string" || !/^[A-Za-z0-9_-]{43}$/.test(value.y)) return null;
  return { kty: "EC", crv: "P-256", x: value.x, y: value.y };
}

function canonicalPublicJwk(value: JsonWebKey): JsonWebKey | null {
  return Object.keys(value).sort().join(",") === publicKeyFields.join(",") ? normalizePublicJwk(value) : null;
}

async function isDeviceKeyRecord(value: unknown, cryptoApi: Crypto): Promise<boolean> {
  if (!(isRecord(value) &&
    value.id === "device" &&
    typeof value.deviceId === "string" && uuidPattern.test(value.deviceId) &&
    isRecord(value.publicJwk) &&
    canonicalPublicJwk(value.publicJwk as JsonWebKey) &&
    value.publicJwk.crv === "P-256" &&
    value.privateKey instanceof CryptoKey &&
    value.privateKey.type === "private" && !value.privateKey.extractable &&
    value.privateKey.algorithm.name === "ECDSA" &&
    (value.privateKey.algorithm as EcKeyAlgorithm).namedCurve === "P-256" &&
    value.privateKey.usages.length === 1 && value.privateKey.usages[0] === "sign")) return false;
  try {
    const publicKey = await cryptoApi.subtle.importKey(
      "jwk", canonicalPublicJwk(value.publicJwk as JsonWebKey)!, { name: "ECDSA", namedCurve: "P-256" }, false, ["verify"],
    );
    const payload = new Uint8Array([0, 1, 2, 3]);
    const signature = await cryptoApi.subtle.sign({ name: "ECDSA", hash: "SHA-256" }, value.privateKey, payload as BufferSource);
    return cryptoApi.subtle.verify({ name: "ECDSA", hash: "SHA-256" }, publicKey, signature, payload as BufferSource);
  } catch {
    return false;
  }
}

function asSigner(record: DeviceKeyRecord, cryptoApi: Crypto): StoredDeviceSigner {
  return {
    deviceId: record.deviceId,
    publicJwk: record.publicJwk,
    privateKey: record.privateKey,
    async sign(payload) {
      const signature = await cryptoApi.subtle.sign(
        { name: "ECDSA", hash: "SHA-256" },
        record.privateKey,
        payload as BufferSource,
      );
      return encodeBase64Url(signature);
    },
  };
}

async function generateDevice(cryptoApi: Crypto): Promise<DeviceKeyRecord> {
  const pair = await cryptoApi.subtle.generateKey(
    { name: "ECDSA", namedCurve: "P-256" },
    false,
    ["sign", "verify"],
  );
  if (!(pair.privateKey instanceof CryptoKey) || !(pair.publicKey instanceof CryptoKey)) {
    throw new Error("device-key-unavailable");
  }
  return {
    id: "device",
    deviceId: cryptoApi.randomUUID(),
    publicJwk: normalizePublicJwk(await cryptoApi.subtle.exportKey("jwk", pair.publicKey))!,
    privateKey: pair.privateKey,
  };
}

type KeyPersistence = {
  get(): Promise<DeviceKeyRecord | null>;
  put(value: DeviceKeyRecord): Promise<void>;
  clear(): Promise<void>;
};

export type MemoryDeviceKeyStoreState = { record: DeviceKeyRecord | null };

function createStore(persistence: KeyPersistence, cryptoApi: Crypto): DeviceKeyStore {
  return {
    async load() {
      const record = await persistence.get();
      if (!record) return null;
      if (await isDeviceKeyRecord(record, cryptoApi)) return asSigner(record as DeviceKeyRecord, cryptoApi);
      await persistence.clear();
      return null;
    },
    async getOrCreate() {
      const existing = await persistence.get();
      if (existing && await isDeviceKeyRecord(existing, cryptoApi)) return asSigner(existing as DeviceKeyRecord, cryptoApi);
      if (existing) await persistence.clear();
      const generated = await generateDevice(cryptoApi);
      await persistence.put(generated);
      return asSigner(generated, cryptoApi);
    },
    clear: () => persistence.clear(),
  };
}

export function createMemoryDeviceKeyStore(
  cryptoApi: Crypto = crypto,
  state: MemoryDeviceKeyStoreState = { record: null },
): DeviceKeyStore {
  return createStore({
    async get() { return state.record; },
    async put(value) { state.record = value; },
    async clear() { state.record = null; },
  }, cryptoApi);
}

function requestResult<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.addEventListener("success", () => resolve(request.result));
    request.addEventListener("error", () => reject(request.error ?? new Error("device-key-unavailable")));
  });
}

function transactionComplete(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.addEventListener("complete", () => resolve());
    transaction.addEventListener("abort", () => reject(transaction.error ?? new Error("device-key-unavailable")));
    transaction.addEventListener("error", () => reject(transaction.error ?? new Error("device-key-unavailable")));
  });
}

async function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(databaseName, 1);
    request.addEventListener("upgradeneeded", () => {
      if (!request.result.objectStoreNames.contains(storeName)) {
        request.result.createObjectStore(storeName, { keyPath: "id" });
      }
    });
    request.addEventListener("success", () => resolve(request.result));
    request.addEventListener("error", () => reject(request.error ?? new Error("device-key-unavailable")));
  });
}

function idbPersistence(): KeyPersistence {
  return {
    async get() {
      const database = await openDatabase();
      try {
        const transaction = database.transaction(storeName, "readonly");
        const result = (await requestResult(transaction.objectStore(storeName).get("device"))) as DeviceKeyRecord | null;
        await transactionComplete(transaction);
        return result;
      } finally {
        database.close();
      }
    },
    async put(value) {
      const database = await openDatabase();
      try {
        const transaction = database.transaction(storeName, "readwrite");
        await requestResult(transaction.objectStore(storeName).put(value));
        await transactionComplete(transaction);
      } finally {
        database.close();
      }
    },
    async clear() {
      const database = await openDatabase();
      try {
        const transaction = database.transaction(storeName, "readwrite");
        await requestResult(transaction.objectStore(storeName).clear());
        await transactionComplete(transaction);
      } finally {
        database.close();
      }
    },
  };
}

/** The only production key store: Chrome extension-owned IndexedDB. */
export function createDeviceKeyStore(cryptoApi: Crypto = crypto): DeviceKeyStore {
  return createStore(idbPersistence(), cryptoApi);
}
