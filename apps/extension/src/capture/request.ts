export type BoundedRequestOptions = {
  fetcher?: typeof fetch;
  maxAttempts?: number;
  timeoutMs?: number;
  retrySleep?: (milliseconds: number) => Promise<void>;
};

export type BoundedJsonResponse<T> = {
  response: Response;
  body: T | null;
};

const defaultSleep = (milliseconds: number) =>
  new Promise<void>((resolve) => setTimeout(resolve, milliseconds));

const isRetryableStatus = (status: number) => status === 429 || (status >= 500 && status <= 599);

const requestError = (aborted: boolean) =>
  new Error(aborted ? "capture request timeout" : "capture request failed");

export async function boundedJsonFetch<T>(
  input: string | URL | Request,
  init: RequestInit,
  options: BoundedRequestOptions = {},
): Promise<BoundedJsonResponse<T>> {
  const fetcher = options.fetcher ?? fetch;
  const attempts = Math.max(1, Math.min(options.maxAttempts ?? 2, 3));
  const timeoutMs = Math.max(1, Math.min(options.timeoutMs ?? 10_000, 30_000));
  const retrySleep = options.retrySleep ?? defaultSleep;

  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    let response: Response;
    try {
      response = await fetcher(input, { ...init, signal: controller.signal });
    } catch {
      clearTimeout(timeout);
      if (attempt === attempts - 1) throw requestError(controller.signal.aborted);
      await retrySleep(Math.min(250 * 2 ** attempt, 1000));
      continue;
    }

    if (isRetryableStatus(response.status)) {
      clearTimeout(timeout);
      if (attempt === attempts - 1) return { response, body: null };
      await retrySleep(Math.min(250 * 2 ** attempt, 1000));
      continue;
    }

    if (!response.ok) {
      clearTimeout(timeout);
      return { response, body: null };
    }

    try {
      const body = (await response.json()) as T;
      clearTimeout(timeout);
      return { response, body };
    } catch {
      clearTimeout(timeout);
      if (controller.signal.aborted) {
        if (attempt === attempts - 1) throw requestError(true);
        await retrySleep(Math.min(250 * 2 ** attempt, 1000));
        continue;
      }
      throw new Error("capture response invalid");
    }
  }
  throw new Error("capture request failed");
}
