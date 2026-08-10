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

function encodeBase64Url(value: ArrayBuffer): string {
  const bytes = new Uint8Array(value);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isDeviceKeyRecord(value: unknown): value is DeviceKeyRecord {
  return isRecord(value) &&
    value.id === "device" &&
    typeof value.deviceId === "string" &&
    value.deviceId !== "" &&
    isRecord(value.publicJwk) &&
    value.publicJwk.kty === "EC" &&
    value.publicJwk.crv === "P-256" &&
    value.privateKey instanceof CryptoKey;
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
    publicJwk: await cryptoApi.subtle.exportKey("jwk", pair.publicKey),
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
      return record && isDeviceKeyRecord(record) ? asSigner(record, cryptoApi) : null;
    },
    async getOrCreate() {
      const existing = await persistence.get();
      if (existing && isDeviceKeyRecord(existing)) return asSigner(existing, cryptoApi);
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
        return (await requestResult(transaction.objectStore(storeName).get("device"))) as DeviceKeyRecord | null;
      } finally {
        database.close();
      }
    },
    async put(value) {
      const database = await openDatabase();
      try {
        const transaction = database.transaction(storeName, "readwrite");
        await requestResult(transaction.objectStore(storeName).put(value));
      } finally {
        database.close();
      }
    },
    async clear() {
      const database = await openDatabase();
      try {
        const transaction = database.transaction(storeName, "readwrite");
        await requestResult(transaction.objectStore(storeName).clear());
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
