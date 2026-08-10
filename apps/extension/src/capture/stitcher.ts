import type { CaptureSlice, StitchLimits, StitchedCapture } from "./full-page-types";

type DecodedImage = { width: number; height: number };
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

const safeFailure = (partialReason: NonNullable<StitchedCapture["partialReason"]>): StitchedCapture => ({
  dataUrl: null,
  width: 0,
  height: 0,
  complete: false,
  croppedOverlapPixels: 0,
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

function samePixels(previous: DecodedImage, current: DecodedImage, overlapPixels: number, runtime: StitchRuntime): boolean {
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
    if (data[index] !== data[stride + index] || data[index + 1] !== data[stride + index + 1] || data[index + 2] !== data[stride + index + 2] || data[index + 3] !== data[stride + index + 3]) return false;
  }
  return true;
}

function encodedBytes(dataUrl: string): number {
  const payload = dataUrl.slice(dataUrl.indexOf(",") + 1);
  return Math.ceil((payload.length * 3) / 4);
}

const restrictiveLimit = (value: number, maximum: number) =>
  Number.isFinite(value) && value >= 0 ? Math.min(value, maximum) : 0;
const DIMENSION_TOLERANCE_PX = 1;

export async function stitchSlices(
  slices: readonly CaptureSlice[],
  limits: StitchLimits,
  runtime: StitchRuntime = defaultRuntime(),
): Promise<StitchedCapture> {
  if (slices.length === 0) return safeFailure("empty");
  if (slices.some((slice, index) => slice.sequence !== index || (index > 0 && slice.scrollY < slices[index - 1]!.scrollY))) {
    return safeFailure("invalid-slice-order");
  }
  try {
    const maxPixels = restrictiveLimit(limits.maxPixels, 40_000_000);
    const maxEdge = restrictiveLimit(limits.maxEdge, 32_000);
    const maxBytes = restrictiveLimit(limits.maxBytes, 10 * 1024 * 1024);
    const decoded = await Promise.all(slices.map((slice) => runtime.decode(slice.dataUrl)));
    if (decoded.some((image, index) =>
      Math.abs(image.width - Math.round(slices[index]!.viewport.width * slices[index]!.viewport.devicePixelRatio)) > DIMENSION_TOLERANCE_PX ||
      Math.abs(image.height - Math.round(slices[index]!.viewport.height * slices[index]!.viewport.devicePixelRatio)) > DIMENSION_TOLERANCE_PX,
    )) return safeFailure("dimension-mismatch");
    const firstImage = decoded[0]!;
    if (decoded.some((image) =>
      Math.abs(image.width - firstImage.width) > DIMENSION_TOLERANCE_PX ||
      Math.abs(image.height - firstImage.height) > DIMENSION_TOLERANCE_PX,
    )) return safeFailure("dimension-mismatch");
    let totalHeight = 0;
    let width = 0;
    let croppedOverlapPixels = 0;
    const crops: number[] = [];
    for (let index = 0; index < decoded.length; index += 1) {
      const image = decoded[index]!;
      width = Math.max(width, image.width);
      let crop = 0;
      if (index > 0) {
        const previous = slices[index - 1]!;
        const current = slices[index]!;
        const previousImage = decoded[index - 1]!;
        const overlap = Math.max(0, Math.min(previousImage.height, image.height, Math.round((previous.scrollY + previous.viewport.height - current.scrollY) * current.viewport.devicePixelRatio)));
        if (
          overlap > 0 &&
          previous.viewport.width === current.viewport.width &&
          previous.viewport.height === current.viewport.height &&
          previous.viewport.devicePixelRatio === current.viewport.devicePixelRatio &&
          previousImage.width === image.width &&
          samePixels(previousImage, image, overlap, runtime)
        ) {
          crop = overlap;
          croppedOverlapPixels += overlap;
        }
      }
      crops.push(crop);
      totalHeight += image.height - crop;
    }
    if (width > maxEdge || totalHeight > maxEdge) return safeFailure("edge-limit");
    if (width * totalHeight > maxPixels) return safeFailure("pixel-limit");
    const canvas = runtime.createCanvas(width, totalHeight);
    const context = canvas.getContext("2d");
    if (!context) return safeFailure("canvas-failed");
    let destinationY = 0;
    decoded.forEach((image, index) => {
      const crop = crops[index]!;
      const height = image.height - crop;
      context.drawImage(image, 0, crop, image.width, height, 0, destinationY, image.width, height);
      destinationY += height;
    });
    const dataUrl = canvas.toDataURL("image/png");
    if (encodedBytes(dataUrl) > maxBytes) return safeFailure("encoded-size");
    return { dataUrl, width, height: totalHeight, complete: true, croppedOverlapPixels };
  } catch {
    return safeFailure("canvas-failed");
  }
}
