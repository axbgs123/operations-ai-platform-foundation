import { describe, expect, it, vi } from "vitest";

import { createBrowserScrollCaptureDriver, ScrollCaptureDriver, type ScrollCaptureDriverDependencies } from "../src/capture/scroll-driver";

function createPage(overrides: Partial<ScrollCaptureDriverDependencies> = {}) {
  let scrollY = 420;
  let height = 2_000;
  let url = "https://creator.douyin.com/creator-micro/content/manage";
  let signature = "douyin:stable";
  let dpr = 1;
  let viewportWidth = 100;
  let now = 0;
  const stop = new AbortController();
  const scrollTo = vi.fn(({ top }: { top: number }) => { scrollY = top; });
  const capture = vi.fn(async () => `data:image/png;base64,${capture.mock.calls.length}`);
  const page = {
    getScrollY: () => scrollY,
    getMetrics: () => ({ scrollHeight: height, viewportWidth, viewportHeight: 100, devicePixelRatio: dpr }),
    getUrl: () => url,
    getSignature: () => signature,
    scrollTo,
    capture,
    now: () => now,
    wait: async (milliseconds: number) => { now += milliseconds; },
    signal: stop.signal,
    ...overrides,
  };
  return {
    page,
    capture,
    scrollTo,
    stop,
    setHeight: (next: number) => { height = next; },
    setUrl: (next: string) => { url = next; },
    setSignature: (next: string) => { signature = next; },
    setDpr: (next: number) => { dpr = next; },
    setViewportWidth: (next: number) => { viewportWidth = next; },
    advance: (milliseconds: number) => { now += milliseconds; },
  };
}

describe("ScrollCaptureDriver", () => {
  it("stops after 30 slices and always restores the original scroll position", async () => {
    const fixture = createPage({ getMetrics: () => ({ scrollHeight: 9_999, viewportWidth: 100, viewportHeight: 100, devicePixelRatio: 1 }) });
    const result = await new ScrollCaptureDriver(fixture.page).capture({ maxSlices: 30, timeoutMs: 20_000 });
    expect(result.slices).toHaveLength(30);
    expect(result.complete).toBe(false);
    expect(result.stopReason).toBe("slice-limit");
    expect(fixture.scrollTo).toHaveBeenLastCalledWith({ top: 420, behavior: "instant" });
  });

  it("enforces the 30-slice and 20-second hard bounds even when callers request more", async () => {
    const fixture = createPage({ getMetrics: () => ({ scrollHeight: 99_999, viewportWidth: 100, viewportHeight: 100, devicePixelRatio: 1 }) });
    const result = await new ScrollCaptureDriver(fixture.page).capture({ maxSlices: 99, timeoutMs: 99_000 });
    expect(result).toMatchObject({ complete: false, stopReason: "slice-limit" });
    expect(result.slices).toHaveLength(30);
  });

  it("requires two stable bottom observations and accommodates lazy height growth", async () => {
    const fixture = createPage();
    fixture.capture.mockImplementation(async () => {
      if (fixture.capture.mock.calls.length === 2) fixture.setHeight(2_100);
      return "data:image/png;base64,slice";
    });
    const result = await new ScrollCaptureDriver(fixture.page).capture({ maxSlices: 30, timeoutMs: 20_000 });
    expect(result.complete).toBe(true);
    expect(result.stopReason).toBe("bottom");
    expect(result.slices).toHaveLength(18);
  });

  it("spaces screenshots by at least 500ms and reports a time limit partial", async () => {
    const timestamps: number[] = [];
    const fixture = createPage({
      getMetrics: () => ({ scrollHeight: 9_999, viewportWidth: 100, viewportHeight: 100, devicePixelRatio: 1 }),
    });
    fixture.capture.mockImplementation(async () => { timestamps.push(fixture.page.now!()); return "data:image/png;base64,slice"; });
    const result = await new ScrollCaptureDriver(fixture.page).capture({ maxSlices: 30, timeoutMs: 1_001 });
    expect(result.complete).toBe(false);
    expect(result.stopReason).toBe("time-limit");
    expect(timestamps).toEqual([0, 500, 1_000]);
  });

  it("stops on cancellation or page drift and restores scrolling in finally", async () => {
    const cancelled = createPage();
    cancelled.capture.mockImplementation(async () => { cancelled.stop.abort(); return "data:image/png;base64,slice"; });
    await expect(new ScrollCaptureDriver(cancelled.page).capture({ maxSlices: 30, timeoutMs: 20_000 }))
      .resolves.toMatchObject({ complete: false, partialReason: "cancelled" });
    expect(cancelled.scrollTo).toHaveBeenLastCalledWith({ top: 420, behavior: "instant" });

    const drifted = createPage();
    drifted.capture.mockImplementation(async () => { drifted.setSignature("douyin:changed"); return "data:image/png;base64,slice"; });
    await expect(new ScrollCaptureDriver(drifted.page).capture({ maxSlices: 30, timeoutMs: 20_000 }))
      .resolves.toMatchObject({ complete: false, partialReason: "page-drift" });
    expect(drifted.scrollTo).toHaveBeenLastCalledWith({ top: 420, behavior: "instant" });
  });

  it("stops safely when URL, layout, or DPR drifts", async () => {
    for (const mutate of [
      (fixture: ReturnType<typeof createPage>) => fixture.setUrl("https://creator.douyin.com/creator-micro/content/manage?changed"),
      (fixture: ReturnType<typeof createPage>) => fixture.setViewportWidth(101),
      (fixture: ReturnType<typeof createPage>) => fixture.setDpr(2),
    ]) {
      const fixture = createPage();
      fixture.capture.mockImplementation(async () => { mutate(fixture); return "data:image/png;base64,slice"; });
      await expect(new ScrollCaptureDriver(fixture.page).capture({ maxSlices: 30, timeoutMs: 20_000 }))
        .resolves.toMatchObject({ complete: false, partialReason: "page-drift" });
    }
  });

  it("does not retain a slow screenshot that completes after the absolute deadline", async () => {
    const fixture = createPage();
    fixture.capture.mockImplementation(async () => { fixture.advance(20_000); return "data:image/png;base64,late"; });
    await expect(new ScrollCaptureDriver(fixture.page).capture({ maxSlices: 30, timeoutMs: 20_000 }))
      .resolves.toMatchObject({ complete: false, stopReason: "time-limit", slices: [] });
    expect(fixture.scrollTo).toHaveBeenLastCalledWith({ top: 420, behavior: "instant" });
  });

  it("truncates screenshot spacing waits to the remaining deadline budget", async () => {
    const fixture = createPage({ getMetrics: () => ({ scrollHeight: 9_999, viewportWidth: 100, viewportHeight: 100, devicePixelRatio: 1 }) });
    const waits: number[] = [];
    fixture.page.wait = async (milliseconds) => { waits.push(milliseconds); fixture.advance(milliseconds + 1); };
    fixture.capture.mockImplementation(async () => { fixture.advance(400); return "data:image/png;base64,slice"; });
    await expect(new ScrollCaptureDriver(fixture.page).capture({ maxSlices: 30, timeoutMs: 600 }))
      .resolves.toMatchObject({ complete: false, stopReason: "time-limit" });
    expect(waits).toEqual([200]);
  });

  it("treats non-finite or negative driver bounds as restrictive instead of permitting capture", async () => {
    const fixture = createPage();
    await expect(new ScrollCaptureDriver(fixture.page).capture({ maxSlices: Number.NaN, timeoutMs: 20_000 }))
      .resolves.toMatchObject({ stopReason: "slice-limit", slices: [] });
    await expect(new ScrollCaptureDriver(createPage().page).capture({ maxSlices: 30, timeoutMs: Number.POSITIVE_INFINITY }))
      .resolves.toMatchObject({ stopReason: "time-limit", slices: [] });
    await expect(new ScrollCaptureDriver(createPage().page).capture({ maxSlices: -1, timeoutMs: 20_000 }))
      .resolves.toMatchObject({ stopReason: "slice-limit", slices: [] });
  });

  it("resets stable-bottom counting if the page grows between bottom observations", async () => {
    const fixture = createPage();
    let grew = false;
    fixture.capture.mockImplementation(async () => {
      if (fixture.capture.mock.calls.length === 17 && !grew) { fixture.setHeight(2_100); grew = true; }
      return "data:image/png;base64,slice";
    });
    const result = await new ScrollCaptureDriver(fixture.page).capture({ maxSlices: 30, timeoutMs: 20_000 });
    expect(result).toMatchObject({ complete: true, stopReason: "bottom" });
    expect(result.slices.length).toBeGreaterThan(17);
  });

  it("uses a live browser signature provider rather than the startup signature", async () => {
    let scrollY = 0;
    let liveSignature = "signature:initial";
    const pageWindow = {
      scrollY, innerWidth: 100, innerHeight: 100, devicePixelRatio: 1,
      location: { href: "https://creator.douyin.com/creator-micro/content/manage" },
      scrollTo: ({ top }: { top: number }) => { scrollY = top; }, addEventListener: () => undefined, removeEventListener: () => undefined,
    } as unknown as Window;
    const pageDocument = {
      documentElement: { scrollHeight: 100 }, body: { scrollHeight: 100 }, visibilityState: "visible",
      addEventListener: () => undefined, removeEventListener: () => undefined,
    } as unknown as Document;
    const driver = createBrowserScrollCaptureDriver({
      context: { platform: "douyin", pageVersion: "v1", pageSignature: "signature:initial" },
      getSignature: () => liveSignature,
      window: pageWindow,
      document: pageDocument,
      capture: async () => { liveSignature = "signature:drifted"; return "data:image/png;base64,slice"; },
    });
    await expect(driver.capture({ maxSlices: 30, timeoutMs: 20_000 }))
      .resolves.toMatchObject({ complete: false, partialReason: "page-drift" });
  });
});
