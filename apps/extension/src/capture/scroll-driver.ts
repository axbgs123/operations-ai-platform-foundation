import type { CapturePlatform, CaptureSlice, CaptureViewport, FullPageCaptureResult, PartialCaptureReason } from "./full-page-types";

export type ScrollCaptureOptions = {
  maxSlices: number;
  timeoutMs: number;
};

export type ScrollPageMetrics = {
  scrollHeight: number;
  viewportWidth: number;
  viewportHeight: number;
  devicePixelRatio: number;
};

export type ScrollCaptureDriverDependencies = {
  getScrollY(): number;
  getMetrics(): ScrollPageMetrics;
  getUrl(): string;
  getSignature(): string;
  getContext?(): { platform: CapturePlatform; pageVersion: string; pageSignature?: string };
  scrollTo(position: { top: number; behavior: "instant" }): void;
  capture(slice: Omit<CaptureSlice, "dataUrl">, options?: { deadlineAt: number; signal: AbortSignal }): Promise<string>;
  now?(): number;
  wait?(milliseconds: number): Promise<void>;
  signal?: AbortSignal;
  /** Browser adapters use this to surface visibility, pagehide, and blur immediately. */
  getInterruptionReason?(): Exclude<PartialCaptureReason, "cancelled" | "page-drift" | "capture-failed"> | null;
  cleanup?(): void;
};

const MIN_CAPTURE_INTERVAL_MS = 500;
const MAX_SLICES = 30;
const MAX_TIMEOUT_MS = 20_000;
const defaultWait = (milliseconds: number) => new Promise<void>((resolve) => setTimeout(resolve, milliseconds));
const restrictiveBound = (value: number, maximum: number) =>
  Number.isFinite(value) && value >= 0 ? Math.min(value, maximum) : 0;

export class ScrollCaptureDriver {
  constructor(private readonly dependencies: ScrollCaptureDriverDependencies) {}

  async capture(options: ScrollCaptureOptions): Promise<FullPageCaptureResult> {
    const { dependencies } = this;
    const now = dependencies.now ?? Date.now;
    const wait = dependencies.wait ?? defaultWait;
    const originalScrollY = dependencies.getScrollY();
    const initial = dependencies.getMetrics();
    const initialUrl = dependencies.getUrl();
    const initialSignature = dependencies.getSignature();
    const context = dependencies.getContext?.() ?? {
      platform: "douyin" as const,
      pageVersion: "unknown",
      pageSignature: initialSignature,
    };
    const startedAt = now();
    const maxSlices = restrictiveBound(options.maxSlices, MAX_SLICES);
    const timeoutMs = restrictiveBound(options.timeoutMs, MAX_TIMEOUT_MS);
    const deadlineAt = startedAt + timeoutMs;
    const slices: CaptureSlice[] = [];
    let lastCaptureAt: number | null = null;
    let stableBottomCount = 0;
    let observedBottom: { scrollHeight: number; bottomY: number } | null = null;

    const partial = (partialReason: PartialCaptureReason): FullPageCaptureResult => ({
      slices,
      complete: false,
      // The public bound enum stays stable; partialReason carries the exact safe-stop disclosure.
      stopReason: "time-limit",
      originalScrollY,
      partialReason,
    });

    const interrupted = (): PartialCaptureReason | null => {
      if (dependencies.signal?.aborted) return "cancelled";
      const external = dependencies.getInterruptionReason?.();
      if (external) return external;
      const metrics = dependencies.getMetrics();
      if (
        dependencies.getUrl() !== initialUrl ||
        dependencies.getSignature() !== initialSignature ||
        metrics.viewportWidth !== initial.viewportWidth ||
        metrics.viewportHeight !== initial.viewportHeight ||
        metrics.devicePixelRatio !== initial.devicePixelRatio
      ) {
        return "page-drift";
      }
      return null;
    };

    try {
      // A full-page capture always begins at the document top. The original
      // position is retained exclusively for the finally restoration below.
      dependencies.scrollTo({ top: 0, behavior: "instant" });
      while (true) {
        const earlyStop = interrupted();
        if (earlyStop) return partial(earlyStop);
        if (now() >= deadlineAt) {
          return { slices, complete: false, stopReason: "time-limit", originalScrollY };
        }
        if (slices.length >= maxSlices) {
          return { slices, complete: false, stopReason: "slice-limit", originalScrollY };
        }
        if (lastCaptureAt !== null) {
          const remainingSpacing = MIN_CAPTURE_INTERVAL_MS - (now() - lastCaptureAt);
          if (remainingSpacing > 0) await wait(Math.min(remainingSpacing, Math.max(0, deadlineAt - now())));
          if (now() >= deadlineAt) {
            return { slices, complete: false, stopReason: "time-limit", originalScrollY };
          }
          const delayedStop = interrupted();
          if (delayedStop) return partial(delayedStop);
        }

        const metrics = dependencies.getMetrics();
        const scrollY = dependencies.getScrollY();
        const sliceWithoutData: Omit<CaptureSlice, "dataUrl"> = {
          sequence: slices.length,
          scrollY,
          url: initialUrl,
          platform: context.platform,
          pageVersion: context.pageVersion,
          pageSignature: context.pageSignature ?? initialSignature,
          viewport: {
            width: metrics.viewportWidth,
            height: metrics.viewportHeight,
            devicePixelRatio: metrics.devicePixelRatio,
          },
        };
        const remainingCaptureMs = deadlineAt - now();
        if (remainingCaptureMs <= 0) {
          return { slices, complete: false, stopReason: "time-limit", originalScrollY };
        }
        const captureAbort = new AbortController();
        const late = Symbol("deadline");
        const cancelled = Symbol("cancelled");
        const onParentAbort = () => captureAbort.abort();
        dependencies.signal?.addEventListener("abort", onParentAbort, { once: true });
        const captureResult = dependencies.capture(sliceWithoutData, { deadlineAt, signal: captureAbort.signal })
          .then((dataUrl) => dataUrl, () => null);
        let deadlineTimer: ReturnType<typeof setTimeout> | undefined;
        const timeout = new Promise<string | null | typeof late>((resolve) => { deadlineTimer = setTimeout(() => {
          captureAbort.abort();
          resolve(late);
        }, remainingCaptureMs); });
        const parentAbort = new Promise<typeof cancelled>((resolve) => {
          if (dependencies.signal?.aborted) resolve(cancelled);
          else dependencies.signal?.addEventListener("abort", () => resolve(cancelled), { once: true });
        });
        const dataUrl = await Promise.race([captureResult, timeout, parentAbort]);
        if (deadlineTimer !== undefined) clearTimeout(deadlineTimer);
        dependencies.signal?.removeEventListener("abort", onParentAbort);
        if (dataUrl === cancelled) return partial("cancelled");
        if (dataUrl === late || now() >= deadlineAt) {
          return { slices, complete: false, stopReason: "time-limit", originalScrollY };
        }
        if (dataUrl === null) {
          return partial("capture-failed");
        }
        slices.push({ ...sliceWithoutData, dataUrl });
        lastCaptureAt = now();

        const afterCaptureStop = interrupted();
        if (afterCaptureStop) return partial(afterCaptureStop);
        const latest = dependencies.getMetrics();
        const bottomY = Math.max(0, latest.scrollHeight - latest.viewportHeight);
        if (dependencies.getScrollY() >= bottomY) {
          stableBottomCount = observedBottom?.scrollHeight === latest.scrollHeight && observedBottom.bottomY === bottomY
            ? stableBottomCount + 1
            : 1;
          observedBottom = { scrollHeight: latest.scrollHeight, bottomY };
          if (stableBottomCount >= 2) {
            return { slices, complete: true, stopReason: "bottom", originalScrollY };
          }
        } else {
          stableBottomCount = 0;
          observedBottom = null;
        }
        dependencies.scrollTo({ top: Math.min(bottomY, dependencies.getScrollY() + latest.viewportHeight), behavior: "instant" });
      }
    } finally {
      try {
        dependencies.scrollTo({ top: originalScrollY, behavior: "instant" });
      } catch {
        // Restoration is best-effort only; never mask a capture safe-stop with a page scroll error.
      }
      dependencies.cleanup?.();
    }
  }
}

/** Content-side adapter. It observes page lifecycle changes and always delegates restoration to capture(). */
export function createBrowserScrollCaptureDriver(options: {
  context: { platform: CapturePlatform; pageVersion: string; pageSignature: string };
  capture(slice: Omit<CaptureSlice, "dataUrl">, options?: { deadlineAt: number; signal: AbortSignal }): Promise<string>;
  getSignature?: () => string;
  signal?: AbortSignal;
  window?: Window;
  document?: Document;
}): ScrollCaptureDriver {
  const pageWindow = options.window ?? window;
  const pageDocument = options.document ?? document;
  let interruption: "page-hidden" | "pagehide" | "window-blur" | null = null;
  const onVisibility = () => { if (pageDocument.visibilityState !== "visible") interruption = "page-hidden"; };
  const onPagehide = () => { interruption = "pagehide"; };
  const onBlur = () => { interruption = "window-blur"; };
  pageDocument.addEventListener("visibilitychange", onVisibility, { once: true });
  pageWindow.addEventListener("pagehide", onPagehide, { once: true });
  pageWindow.addEventListener("blur", onBlur, { once: true });
  const root = () => pageDocument.documentElement;
  return new ScrollCaptureDriver({
    getScrollY: () => pageWindow.scrollY,
    getMetrics: () => ({
      scrollHeight: Math.max(root().scrollHeight, pageDocument.body?.scrollHeight ?? 0),
      viewportWidth: pageWindow.innerWidth,
      viewportHeight: pageWindow.innerHeight,
      devicePixelRatio: pageWindow.devicePixelRatio || 1,
    }),
    getUrl: () => pageWindow.location.href,
    getSignature: options.getSignature ?? (() => options.context.pageSignature),
    getContext: () => options.context,
    scrollTo: ({ top }) => pageWindow.scrollTo({ top, behavior: "instant" as ScrollBehavior }),
    capture: options.capture,
    signal: options.signal,
    getInterruptionReason: () => interruption,
    cleanup: () => {
      pageDocument.removeEventListener("visibilitychange", onVisibility);
      pageWindow.removeEventListener("pagehide", onPagehide);
      pageWindow.removeEventListener("blur", onBlur);
    },
  });
}
