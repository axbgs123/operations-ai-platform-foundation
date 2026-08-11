import { encodedDataUrlByteLength } from "./data-url";
import type { CaptureSlice, StitchLimits, StitchedCapture } from "./full-page-types";

type DecodedImage = { width: number; height: number; close?(): void };
type CanvasContext = {
  drawImage(image: unknown, ...values: number[]): void;
  getImageData(x: number, y: number, width: number, height: number): { data: Uint8ClampedArray };
};
type Canvas = { getContext(type: "2d"): CanvasContext | null; toDataURL(type?: string): string };
export type StitchRuntime = {
  decode(dataUrl: string): Promise<DecodedImage>;
  createCanvas(width: number, height: number): Canvas;
  /** Test seam only. Production uses pixel data from a canvas. */
  rowsMatch?(previous: DecodedImage, current: DecodedImage, overlapPixels: number): boolean;
};

const safeFailure = (
  partialReason: NonNullable<StitchedCapture["partialReason"]>,
  sliceCount = 0,
): StitchedCapture => ({
  dataUrl: null,
  width: 0,
  height: 0,
  complete: false,
  croppedOverlapPixels: 0,
  sliceCount,
  partialReason,
});

function defaultRuntime(): StitchRuntime {
  return {
    async decode(dataUrl) {
      if (typeof createImageBitmap === "function") {
        const blob = await (await fetch(dataUrl)).blob();
        return createImageBitmap(blob);
      }
      const image = new Image();
      await new Promise<void>((resolve, reject) => {
        image.onload = () => resolve();
        image.onerror = () => reject(new Error("image-decode-failed"));
        image.src = dataUrl;
      });
      return image;
    },
    createCanvas(width, height) {
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      return canvas as unknown as Canvas;
    },
  };
}

function samePixels(
  previous: DecodedImage,
  current: DecodedImage,
  overlapPixels: number,
  runtime: StitchRuntime,
): boolean {
  if (overlapPixels <= 0) return false;
  if (runtime.rowsMatch) return runtime.rowsMatch(previous, current, overlapPixels);
  const width = Math.min(previous.width, current.width);
  const sampleHeight = Math.min(overlapPixels, 64);
  const canvas = runtime.createCanvas(width, sampleHeight * 2);
  const context = canvas.getContext("2d");
  if (!context) throw new Error("canvas-context-unavailable");
  context.drawImage(previous, 0, previous.height - sampleHeight, width, sampleHeight, 0, 0, width, sampleHeight);
  context.drawImage(current, 0, overlapPixels - sampleHeight, width, sampleHeight, 0, sampleHeight, width, sampleHeight);
  const data = context.getImageData(0, 0, width, sampleHeight * 2).data;
  const stride = width * sampleHeight * 4;
  for (let index = 0; index < stride; index += Math.max(4, Math.floor(stride / 256 / 4) * 4)) {
    if (
      data[index] !== data[stride + index] ||
      data[index + 1] !== data[stride + index + 1] ||
      data[index + 2] !== data[stride + index + 2] ||
      data[index + 3] !== data[stride + index + 3]
    ) return false;
  }
  return true;
}

const restrictiveLimit = (value: number, maximum: number) =>
  Number.isFinite(value) && value >= 0 ? Math.min(value, maximum) : 0;
const DIMENSION_TOLERANCE_PX = 1;

type PlannedSlice = { slice: CaptureSlice; width: number; height: number };

function planBoundedPrefix(
  slices: readonly CaptureSlice[],
  maxPixels: number,
  maxEdge: number,
  maxBytes: number,
): { planned: PlannedSlice[]; partialReason?: "pixel-limit" | "edge-limit" | "encoded-size" | "dimension-mismatch" } {
  const planned: PlannedSlice[] = [];
  let rawHeight = 0;
  let sourceBytes = 0;
  let firstWidth: number | null = null;
  let firstHeight: number | null = null;
  for (const slice of slices) {
    const values = [slice.viewport.width, slice.viewport.height, slice.viewport.devicePixelRatio];
    if (!values.every((value) => Number.isFinite(value) && value > 0)) {
      return { planned: [], partialReason: "dimension-mismatch" };
    }
    const width = Math.round(slice.viewport.width * slice.viewport.devicePixelRatio);
    const height = Math.round(slice.viewport.height * slice.viewport.devicePixelRatio);
    if (!Number.isSafeInteger(width) || !Number.isSafeInteger(height) || width <= 0 || height <= 0) {
      return { planned: [], partialReason: "dimension-mismatch" };
    }
    if (firstWidth !== null && (
      Math.abs(width - firstWidth) > DIMENSION_TOLERANCE_PX ||
      Math.abs(height - firstHeight!) > DIMENSION_TOLERANCE_PX
    )) {
      return { planned: [], partialReason: "dimension-mismatch" };
    }
    firstWidth ??= width;
    firstHeight ??= height;
    let bytes: number;
    try {
      bytes = encodedDataUrlByteLength(slice.dataUrl);
    } catch {
      return { planned, partialReason: "encoded-size" };
    }
    const nextHeight = rawHeight + height;
    if (width > maxEdge || nextHeight > maxEdge) return { planned, partialReason: "edge-limit" };
    if (width * nextHeight > maxPixels) return { planned, partialReason: "pixel-limit" };
    if (sourceBytes + bytes > maxBytes) return { planned, partialReason: "encoded-size" };
    planned.push({ slice, width, height });
    rawHeight = nextHeight;
    sourceBytes += bytes;
  }
  return { planned };
}

export async function stitchSlices(
  slices: readonly CaptureSlice[],
  limits: StitchLimits,
  runtime: StitchRuntime = defaultRuntime(),
): Promise<StitchedCapture> {
  if (slices.length === 0) return safeFailure("empty");
  if (slices.some((slice, index) =>
    slice.sequence !== index || (index > 0 && slice.scrollY < slices[index - 1]!.scrollY))) {
    return safeFailure("invalid-slice-order");
  }
  const maxPixels = restrictiveLimit(limits.maxPixels, 40_000_000);
  const maxEdge = restrictiveLimit(limits.maxEdge, 32_000);
  const maxBytes = restrictiveLimit(limits.maxBytes, 10 * 1024 * 1024);
  const plan = planBoundedPrefix(slices, maxPixels, maxEdge, maxBytes);
  if (plan.planned.length === 0) {
    return safeFailure(plan.partialReason ?? "empty");
  }

  const decoded: DecodedImage[] = [];
  try {
    for (const planned of plan.planned) {
      const image = await runtime.decode(planned.slice.dataUrl);
      decoded.push(image);
      if (
        Math.abs(image.width - planned.width) > DIMENSION_TOLERANCE_PX ||
        Math.abs(image.height - planned.height) > DIMENSION_TOLERANCE_PX
      ) return safeFailure("dimension-mismatch", decoded.length);
    }

    let totalHeight = 0;
    let croppedOverlapPixels = 0;
    let overlapUnverified = false;
    const crops: number[] = [];
    for (let index = 0; index < decoded.length; index += 1) {
      const image = decoded[index]!;
      let crop = 0;
      if (index > 0) {
        const previous = plan.planned[index - 1]!.slice;
        const current = plan.planned[index]!.slice;
        const previousImage = decoded[index - 1]!;
        const overlap = Math.max(0, Math.min(
          previousImage.height,
          image.height,
          Math.round(
            (previous.scrollY + previous.viewport.height - current.scrollY) *
              current.viewport.devicePixelRatio,
          ),
        ));
        if (overlap > 0) {
          if (
            previous.viewport.width === current.viewport.width &&
            previous.viewport.height === current.viewport.height &&
            previous.viewport.devicePixelRatio === current.viewport.devicePixelRatio &&
            previousImage.width === image.width &&
            samePixels(previousImage, image, overlap, runtime)
          ) {
            crop = overlap;
            croppedOverlapPixels += overlap;
          } else {
            overlapUnverified = true;
          }
        }
      }
      crops.push(crop);
      totalHeight += image.height - crop;
    }

    const width = decoded[0]!.width;
    const canvas = runtime.createCanvas(width, totalHeight);
    const context = canvas.getContext("2d");
    if (!context) return safeFailure("canvas-failed", decoded.length);
    let destinationY = 0;
    decoded.forEach((image, index) => {
      const crop = crops[index]!;
      const height = image.height - crop;
      context.drawImage(image, 0, crop, image.width, height, 0, destinationY, image.width, height);
      destinationY += height;
    });
    const dataUrl = canvas.toDataURL("image/png");
    let outputBytes: number;
    try {
      outputBytes = encodedDataUrlByteLength(dataUrl);
    } catch {
      return safeFailure("encoded-size", decoded.length);
    }
    if (outputBytes > maxBytes) return safeFailure("encoded-size", decoded.length);
    const partialReason = plan.partialReason ?? (overlapUnverified ? "overlap-unverified" : undefined);
    return {
      dataUrl,
      width,
      height: totalHeight,
      complete: partialReason === undefined,
      croppedOverlapPixels,
      sliceCount: decoded.length,
      ...(partialReason ? { partialReason } : {}),
    };
  } catch {
    return safeFailure("canvas-failed", decoded.length);
  } finally {
    for (const image of decoded) image.close?.();
  }
}

export { encodedDataUrlByteLength } from "./data-url";
