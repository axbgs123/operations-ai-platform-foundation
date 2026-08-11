import { describe, expect, it, vi } from "vitest";

import { encodedDataUrlByteLength, stitchSlices } from "../src/capture/stitcher";
import type { CaptureSlice } from "../src/capture/full-page-types";

const slice = (sequence: number, scrollY: number, dataUrl = `data:image/png;base64,${Buffer.from(String(sequence)).toString("base64")}`): CaptureSlice => ({
  dataUrl,
  sequence,
  scrollY,
  url: "https://creator.douyin.com/creator-micro/content/manage",
  platform: "douyin",
  pageVersion: "douyin-visible-tab-v1",
  pageSignature: "douyin:stable",
  viewport: { width: 100, height: 100, devicePixelRatio: 1 },
});

const runtime = (rowsMatch = true, encoded = "data:image/png;base64,c21hbGw=") => ({
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

  it("stitches the five retained synthetic slices to 1280x4000", async () => {
    const slices = [0, 800, 1_600, 2_400, 3_200].map((scrollY, sequence) => ({
      ...slice(sequence, scrollY),
      viewport: { width: 1_280, height: 800, devicePixelRatio: 1 },
    }));
    const longPageRuntime = runtime();
    longPageRuntime.decode = async () => ({ width: 1_280, height: 800 });

    const result = await stitchSlices(slices, limits, longPageRuntime);

    expect(result).toMatchObject({ complete: true, width: 1_280, height: 4_000, croppedOverlapPixels: 0 });
  });

  it("keeps uncertain sticky-looking overlap but discloses the result as partial", async () => {
    const result = await stitchSlices([slice(0, 0), slice(1, 80)], limits, runtime(false));
    expect(result).toMatchObject({
      complete: false,
      partialReason: "overlap-unverified",
      height: 200,
      croppedOverlapPixels: 0,
      dataUrl: "data:image/png;base64,c21hbGw=",
    });
  });

  it("discloses partial output at pixel, edge, and encoded payload limits", async () => {
    await expect(stitchSlices([slice(0, 0)], { ...limits, maxPixels: 9_999 }, runtime()))
      .resolves.toMatchObject({ complete: false, partialReason: "pixel-limit", dataUrl: null });
    await expect(stitchSlices([slice(0, 0)], { ...limits, maxEdge: 99 }, runtime()))
      .resolves.toMatchObject({ complete: false, partialReason: "edge-limit", dataUrl: null });
    await expect(stitchSlices([slice(0, 0)], { ...limits, maxBytes: 10 }, runtime(true, `data:image/png;base64,${Buffer.alloc(20).toString("base64")}`)))
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
        toDataURL: () => "data:image/png;base64,c21hbGw=",
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

  it("preflights a 30-slice high-DPR capture, decodes one bounded prefix, and closes every bitmap", async () => {
    const close = vi.fn();
    const decode = vi.fn(async () => ({ width: 2_000, height: 2_000, close }));
    const highDprSlices = Array.from({ length: 30 }, (_value, sequence) => ({
      ...slice(sequence, sequence * 1_000),
      viewport: { width: 1_000, height: 1_000, devicePixelRatio: 2 },
    }));
    const boundedRuntime = {
      decode,
      createCanvas: () => ({
        getContext: () => ({ drawImage: () => undefined, getImageData: () => ({ data: new Uint8ClampedArray() }) }),
        toDataURL: () => "data:image/png;base64,c21hbGw=",
      }),
      rowsMatch: () => true,
    };

    await expect(stitchSlices(highDprSlices, limits, boundedRuntime)).resolves.toMatchObject({
      complete: false,
      partialReason: "pixel-limit",
      sliceCount: 10,
      dataUrl: "data:image/png;base64,c21hbGw=",
    });
    expect(decode).toHaveBeenCalledTimes(10);
    expect(close).toHaveBeenCalledTimes(10);
  });

  it("measures canonical base64 exactly and rejects malformed payloads", () => {
    expect(encodedDataUrlByteLength("data:image/png;base64,TQ==")).toBe(1);
    expect(encodedDataUrlByteLength("data:image/png;base64,TWE=")).toBe(2);
    expect(() => encodedDataUrlByteLength("data:image/png;base64,TQ=")).toThrow("invalid-base64-data-url");
    expect(() => encodedDataUrlByteLength("data:image/png;base64,TQ==junk")).toThrow("invalid-base64-data-url");
  });
});
