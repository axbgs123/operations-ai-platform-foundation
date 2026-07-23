export type ServerValidation =
  | { ok: true; origin: string }
  | { ok: false; reason: string };

function isLoopback(hostname: string): boolean {
  return (
    hostname === "localhost" ||
    hostname === "127.0.0.1" ||
    hostname === "[::1]"
  );
}

export function validateServerOrigin(value: string): ServerValidation {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return { ok: false, reason: "服务器地址无效" };
  }
  if (url.username || url.password || url.hash) {
    return { ok: false, reason: "服务器地址不能包含凭据或片段" };
  }
  if (url.pathname !== "/" || url.search) {
    return { ok: false, reason: "服务器地址只能填写站点根地址" };
  }
  if (
    (url.hostname.includes("localhost") && url.hostname !== "localhost") ||
    (url.hostname.startsWith("127.0.0.1.") && url.hostname !== "127.0.0.1")
  ) {
    return { ok: false, reason: "服务器主机名存在混淆" };
  }
  if (
    url.protocol !== "https:" &&
    !(url.protocol === "http:" && isLoopback(url.hostname))
  ) {
    return { ok: false, reason: "服务器地址必须使用 HTTPS" };
  }
  return { ok: true, origin: url.origin };
}

export function normalizeServerOrigin(value: string): string {
  const result = validateServerOrigin(value);
  if (!result.ok) throw new Error(result.reason);
  return result.origin;
}

export async function clearBinding(store: {
  clear(): Promise<void>;
}): Promise<void> {
  await store.clear();
}
