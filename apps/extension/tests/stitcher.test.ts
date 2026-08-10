import { describe, expect, it } from "vitest";

import { stitchSlices } from "../src/capture/stitcher";
import type { CaptureSlice } from "../src/capture/full-page-types";

const slice = (sequence: number, scrollY: number, dataUrl = `data:image/png;base64,${sequence}`): CaptureSlice => ({
  dataUrl,
  sequence,
  scrollY,
  url: "https://creator.douyin.com/creator-micro/content/manage",
  platform: "douyin",
  pageVersion: "douyin-visible-tab-v1",
  pageSignature: "douyin:stable",
  viewport: { width: 100, height: 100, devicePixelRatio: 1 },
});

const runtime = (rowsMatch = true, encoded = "data:image/png;base64,small") => ({
  decode: async () => ({ width: 100, height: 100 }),
  createCanvas: () => ({
    getContext: () => ({ drawImage: () => undefined, getImageData: () => ({ data: new Uint8ClampedArray([0, 0, 0, 255]) }) }),
    toDataURL: () => encoded,
  }),
  rowsMatch: () => rowsMatch,
});

const limits = { maxPixels: 40_000_000, maxEdge: 32_000, maxBytes: 10 * 1024 * 1024 } as const;

describe("stitchSlices", () => {
  it("crops only a pixel-proven overlap", async () => {
    const result = await stitchSlices([slice(0, 0), slice(1, 80)], limits, runtime());
    expect(result).toMatchObject({ complete: true, width: 100, height: 180, croppedOverlapPixels: 20 });
  });

  it("stitches the six-slice synthetic long-page plan to 1280x4000", async () => {
    const slices = [0, 800, 1_600, 2_400, 3_200, 3_200].map((scrollY, sequence) => ({
      ...slice(sequence, scrollY),
      viewport: { width: 1_280, height: 800, devicePixelRatio: 1 },
    }));
    const longPageRuntime = runtime();
    longPageRuntime.decode = async () => ({ width: 1_280, height: 800 });

    const result = await stitchSlices(slices, limits, longPageRuntime);

    expect(result).toMatchObject({ complete: true, width: 1_280, height: 4_000, croppedOverlapPixels: 800 });
  });

  it("keeps uncertain sticky-looking overlap instead of guessing removal", async () => {
    const result = await stitchSlices([slice(0, 0), slice(1, 80)], limits, runtime(false));
    expect(result).toMatchObject({ complete: true, height: 200, croppedOverlapPixels: 0 });
  });

  it("discloses partial output at pixel, edge, and encoded payload limits", async () => {
    await expect(stitchSlices([slice(0, 0)], { ...limits, maxPixels: 9_999 }, runtime()))
      .resolves.toMatchObject({ complete: false, partialReason: "pixel-limit", dataUrl: null });
    await expect(stitchSlices([slice(0, 0)], { ...limits, maxEdge: 99 }, runtime()))
      .resolves.toMatchObject({ complete: false, partialReason: "edge-limit", dataUrl: null });
    await expect(stitchSlices([slice(0, 0)], { ...limits, maxBytes: 10 }, runtime(true, `data:image/png;base64,${"a".repeat(20)}`)))
      .resolves.toMatchObject({ complete: false, partialReason: "encoded-size", dataUrl: null });
  });

  it("fails safe and discloses canvas failures", async () => {
    const failed = runtime();
    failed.createCanvas = () => { throw new Error("canvas unavailable"); };
    await expect(stitchSlices([slice(0, 0)], limits, failed)).resolves.toMatchObject({
      complete: false,
      partialReason: "canvas-failed",
      dataUrl: null,
    });
  });

  it("never permits callers to raise the 40M pixel, 32k edge, or 10MiB encoding caps", async () => {
    const oversized = runtime();
    oversized.decode = async () => ({ width: 32_001, height: 1 });
    await expect(stitchSlices([{ ...slice(0, 0), viewport: { width: 32_001, height: 1, devicePixelRatio: 1 } }], { maxPixels: Number.MAX_SAFE_INTEGER, maxEdge: Number.MAX_SAFE_INTEGER, maxBytes: Number.MAX_SAFE_INTEGER }, oversized))
      .resolves.toMatchObject({ complete: false, partialReason: "edge-limit", dataUrl: null });
  });

  it("treats NaN, infinity, and negative output limits as restrictive", async () => {
    await expect(stitchSlices([slice(0, 0)], { ...limits, maxPixels: Number.NaN }, runtime()))
      .resolves.toMatchObject({ complete: false, partialReason: "pixel-limit" });
    await expect(stitchSlices([slice(0, 0)], { ...limits, maxEdge: Number.POSITIVE_INFINITY }, runtime()))
      .resolves.toMatchObject({ complete: false, partialReason: "edge-limit" });
    await expect(stitchSlices([slice(0, 0)], { ...limits, maxBytes: -1 }, runtime()))
      .resolves.toMatchObject({ complete: false, partialReason: "encoded-size" });
  });

  it("compares the corresponding tail of an overlap larger than 64 pixels", async () => {
    const calls: number[][] = [];
    const pixelRuntime = {
      decode: async () => ({ width: 100, height: 100 }),
      createCanvas: () => ({
        getContext: () => ({
          drawImage: (_image: unknown, ...args: number[]) => { calls.push(args); },
          getImageData: () => ({ data: new Uint8ClampedArray(100 * 64 * 2 * 4).fill(7) }),
        }),
        toDataURL: () => "data:image/png;base64,small",
      }),
    };
    const result = await stitchSlices([slice(0, 0), slice(1, 20)], limits, pixelRuntime);
    expect(result).toMatchObject({ complete: true, croppedOverlapPixels: 80 });
    expect(calls[1]).toEqual([0, 16, 100, 64, 0, 64, 100, 64]);
  });

  it("fails closed when decoded dimensions do not match viewport times DPR", async () => {
    const mismatched = runtime();
    mismatched.decode = async () => ({ width: 98, height: 100 });
    await expect(stitchSlices([slice(0, 0)], limits, mismatched))
      .resolves.toMatchObject({ complete: false, partialReason: "dimension-mismatch", dataUrl: null });
  });

  it("fails closed when otherwise valid decoded slices are mutually inconsistent", async () => {
    let decoded = 0;
    const inconsistent = runtime();
    inconsistent.decode = async () => ({ width: decoded++ === 0 ? 100 : 90, height: 100 });
    await expect(stitchSlices([slice(0, 0), { ...slice(1, 100), viewport: { width: 90, height: 100, devicePixelRatio: 1 } }], limits, inconsistent))
      .resolves.toMatchObject({ complete: false, partialReason: "dimension-mismatch", dataUrl: null });
  });
});
