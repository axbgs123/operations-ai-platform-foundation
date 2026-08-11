import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

import { JSDOM } from "jsdom";
import { describe, expect, it, vi } from "vitest";

import type { ExtensionBinding } from "../src/auth/storage";
import { ScrollCaptureDriver } from "../src/capture/scroll-driver";
import { stitchSlices, type StitchRuntime } from "../src/capture/stitcher";
import type { CaptureSlice } from "../src/capture/full-page-types";
import { CaptureOverlay } from "../src/content/capture-overlay";

type SyntheticImage = {
  width: number;
  height: number;
  rows: Uint32Array;
};

const fixturePath = resolve(
  import.meta.dirname,
  "../../../tests/e2e/fixtures/long-creator-page.html",
);
const limits = {
  maxPixels: 40_000_000,
  maxEdge: 32_000,
  maxBytes: 10 * 1024 * 1024,
} as const;
const binding: ExtensionBinding = {
  serverOrigin: "https://api.ops.example.com",
  webOrigin: "https://app.ops.example.com",
  workspaceId: "00000000-0000-0000-0000-000000000001",
  workspaceName: "Fixture workspace",
  memberDisplayName: "Fixture editor",
  accessToken: "fixture-only-token",
  expiresAt: "2030-01-01T00:00:00Z",
  providerMode: "mock",
  region: null,
};

describe("synthetic long-page component integration", () => {
  it("drives fixture geometry through scroll pixels, stitcher, and the real overlay", async () => {
    const fixtureHtml = await readFile(fixturePath, "utf8");
    const dom = new JSDOM(fixtureHtml);
    const fixtureWindow = dom.window.document.defaultView!;
    const marker = dom.window.document.querySelector<HTMLElement>(
      '[data-e2e-page="synthetic-long-creator"]',
    );
    expect(marker).not.toBeNull();

    const scrollHeight = Number.parseInt(fixtureWindow.getComputedStyle(marker!).height, 10);
    const viewportWidth = Number(marker!.dataset.e2eViewportWidth);
    const viewportHeight = Number(marker!.dataset.e2eViewportHeight);
    expect(scrollHeight).toBe(4_000);
    expect(Number(marker!.dataset.e2eScrollHeight)).toBe(scrollHeight);
    expect(viewportWidth).toBe(1_280);
    expect(viewportHeight).toBe(800);

    let scrollY = 0;
    let now = 0;
    let finalRows = new Uint32Array();
    const screenshots = new Map<string, SyntheticImage>();
    let captureResult: Awaited<ReturnType<ScrollCaptureDriver["capture"]>> | undefined;
    let stitchedResult: Awaited<ReturnType<typeof stitchSlices>> | undefined;
    const captureVisibleTab = vi.fn(async () => {
      throw new Error("real-user-gesture-not-run");
    });

    const stitchRuntime: StitchRuntime = {
      decode: async (dataUrl) => {
        const image = screenshots.get(dataUrl);
        if (!image) throw new Error("synthetic-screenshot-missing");
        return image;
      },
      rowsMatch: (previous, current, overlapPixels) => {
        const previousPixels = (previous as SyntheticImage).rows;
        const currentPixels = (current as SyntheticImage).rows;
        for (let row = 0; row < overlapPixels; row += 1) {
          if (
            previousPixels[previousPixels.length - overlapPixels + row] !==
            currentPixels[row]
          ) {
            return false;
          }
        }
        return true;
      },
      createCanvas: (_width, height) => {
        finalRows = new Uint32Array(height);
        return {
          getContext: () => ({
            drawImage: (image, _sx, sy, _sw, sliceHeight, _dx, dy) => {
              const source = (image as SyntheticImage).rows;
              finalRows.set(source.subarray(sy, sy + sliceHeight), dy);
            },
            getImageData: () => ({ data: new Uint8ClampedArray() }),
          }),
          toDataURL: () =>
            `data:image/png;base64,${Buffer.from("synthetic-stitched-pixels").toString("base64")}`,
        };
      },
    };

    const overlay = CaptureOverlay.mount({
      document: dom.window.document,
      viewport: {
        width: viewportWidth,
        height: viewportHeight,
        devicePixelRatio: 1,
      },
      detect: () => ({
        supported: true,
        platform: "douyin",
        pageVersion: "douyin-visible-tab-v1",
        signature: `fixture:${marker!.dataset.e2ePage}:${scrollHeight}`,
        captureRegion: null,
        sensitiveRegions: [],
      }),
      captureVisibleTab,
      crop: async () => {
        throw new Error("region-crop-not-used");
      },
      redact: async (dataUrl) => dataUrl,
      upload: async () => {
        throw new Error("upload-not-run");
      },
      poll: async () => {
        throw new Error("poll-not-run");
      },
      binding,
      uuid: () => "fixture-full-page-capture",
      nextFrame: async () => undefined,
      mode: "full-page",
      fullPageCapture: async (signal) => {
        const driver = new ScrollCaptureDriver({
          getScrollY: () => scrollY,
          getMetrics: () => ({
            scrollHeight,
            viewportWidth,
            viewportHeight,
            devicePixelRatio: 1,
          }),
          getUrl: () => "https://creator.douyin.com/creator-micro/content/manage",
          getSignature: () => `fixture:${marker!.dataset.e2ePage}:${scrollHeight}`,
          getContext: () => ({
            platform: "douyin",
            pageVersion: "douyin-visible-tab-v1",
            pageSignature: `fixture:${marker!.dataset.e2ePage}:${scrollHeight}`,
          }),
          scrollTo: ({ top }) => {
            scrollY = Math.max(0, Math.min(top, scrollHeight - viewportHeight));
          },
          capture: async (slice: Omit<CaptureSlice, "dataUrl">) => {
            const dataUrl = `data:image/png;base64,${Buffer.from(
              `slice-${slice.scrollY}`,
            ).toString("base64")}`;
            screenshots.set(dataUrl, {
              width: viewportWidth,
              height: viewportHeight,
              rows: Uint32Array.from(
                { length: viewportHeight },
                (_value, row) => slice.scrollY + row,
              ),
            });
            return dataUrl;
          },
          now: () => now,
          wait: async (milliseconds) => {
            now += milliseconds;
          },
          signal,
        });
        captureResult = await driver.capture({
          maxSlices: 30,
          timeoutMs: 20_000,
        });
        stitchedResult = await stitchSlices(
          captureResult.slices,
          limits,
          stitchRuntime,
        );
        if (stitchedResult.dataUrl === null) {
          return {
            dataUrl: null,
            complete: false,
            stopReason:
              stitchedResult.partialReason ?? captureResult.stopReason,
            sliceCount: captureResult.slices.length,
          };
        }
        return {
          dataUrl: stitchedResult.dataUrl,
          width: stitchedResult.width,
          height: stitchedResult.height,
          complete: captureResult.complete && stitchedResult.complete,
          stopReason:
            stitchedResult.partialReason ?? captureResult.stopReason,
          sliceCount: captureResult.slices.length,
        };
      },
    });

    await overlay.startAutomaticCapture();

    expect(captureResult?.slices.map(({ scrollY: position }) => position)).toEqual([
      0,
      800,
      1_600,
      2_400,
      3_200,
    ]);
    expect(stitchedResult).toMatchObject({
      complete: true,
      width: 1_280,
      height: 4_000,
      croppedOverlapPixels: 0,
    });
    expect(finalRows).toHaveLength(4_000);
    expect(Array.from(finalRows).every((value, row) => value === row)).toBe(true);
    expect(overlay.state).toBe("previewing");
    expect(overlay.captureMetadata()).toEqual({
      capture_mode: "full-page",
      complete: true,
      stop_reason: "bottom",
      slice_count: 5,
    });
    expect(overlay.element.textContent).toContain("完整");
    expect(overlay.element.textContent).toContain("采集 5 屏");
    expect(overlay.element.textContent).toContain("1280×4000");
    expect(overlay.element.textContent).toContain("遮挡敏感信息：关");
    expect(overlay.element.textContent).not.toContain("添加遮挡");
    expect(captureVisibleTab).not.toHaveBeenCalled();
  });
});
