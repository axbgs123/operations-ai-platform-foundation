import type { Rect } from "./page-adapters/base";

export type ViewportMetrics = {
  width: number;
  height: number;
  devicePixelRatio: number;
};

const maxUploadBytes = 10 * 1024 * 1024;

const decodeImage = (dataUrl: string): Promise<HTMLImageElement> => {
  if (!dataUrl.startsWith("data:image/")) return Promise.reject(new Error("image-decode-failed"));
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      if (image.naturalWidth <= 0 || image.naturalHeight <= 0) reject(new Error("image-zero-dimensions"));
      else resolve(image);
    };
    image.onerror = () => reject(new Error("image-decode-failed"));
    image.src = dataUrl;
  });
};

const canvas2d = (width: number, height: number) => {
  if (!Number.isSafeInteger(width) || !Number.isSafeInteger(height) || width <= 0 || height <= 0) {
    throw new Error("image-zero-dimensions");
  }
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("image-processing-unavailable");
  return { canvas, context };
};

const pngByteLength = (dataUrl: string) => {
  const [prefix, encoded] = dataUrl.split(",", 2);
  if (prefix !== "data:image/png;base64" || !encoded) throw new Error("invalid-png-output");
  const padding = encoded.endsWith("==") ? 2 : encoded.endsWith("=") ? 1 : 0;
  return Math.floor((encoded.length * 3) / 4) - padding;
};

const controlledPng = (canvas: HTMLCanvasElement) => {
  const output = canvas.toDataURL("image/png");
  if (pngByteLength(output) > maxUploadBytes) throw new Error("image-exceeds-upload-limit");
  return output;
};

export async function cropVisibleTab(
  dataUrl: string,
  selection: Rect,
  viewport: ViewportMetrics,
): Promise<string> {
  const { width, height, devicePixelRatio } = viewport;
  if (
    ![width, height, devicePixelRatio].every((value) => Number.isFinite(value) && value > 0) ||
    selection.x < 0 ||
    selection.y < 0 ||
    selection.width <= 0 ||
    selection.height <= 0 ||
    selection.x + selection.width > width ||
    selection.y + selection.height > height
  ) {
    throw new Error("invalid-crop-region");
  }
  const image = await decodeImage(dataUrl);
  const expectedWidth = width * devicePixelRatio;
  const expectedHeight = height * devicePixelRatio;
  // Browser chrome can introduce sub-pixel rounding. Permit at most 0.5% or
  // two physical pixels, whichever is larger; larger drift is a resize/zoom
  // or capture-surface mismatch and must fail closed.
  const widthTolerance = Math.max(2, expectedWidth * 0.005);
  const heightTolerance = Math.max(2, expectedHeight * 0.005);
  if (
    Math.abs(image.naturalWidth - expectedWidth) > widthTolerance ||
    Math.abs(image.naturalHeight - expectedHeight) > heightTolerance
  ) {
    throw new Error("screenshot-dimension-mismatch");
  }
  const cropWidth = Math.round(selection.width * devicePixelRatio);
  const cropHeight = Math.round(selection.height * devicePixelRatio);
  const { canvas, context } = canvas2d(cropWidth, cropHeight);
  context.drawImage(
    image,
    Math.round(selection.x * devicePixelRatio),
    Math.round(selection.y * devicePixelRatio),
    cropWidth,
    cropHeight,
    0,
    0,
    cropWidth,
    cropHeight,
  );
  return controlledPng(canvas);
}

export async function applyRedactions(dataUrl: string, redactions: Rect[]): Promise<string> {
  const image = await decodeImage(dataUrl);
  const { canvas, context } = canvas2d(image.naturalWidth, image.naturalHeight);
  context.drawImage(image, 0, 0);
  context.fillStyle = "#000000";
  for (const region of redactions) {
    if (
      ![region.x, region.y, region.width, region.height].every(Number.isFinite) ||
      region.width <= 0 ||
      region.height <= 0
    ) {
      throw new Error("invalid-redaction-region");
    }
    const x = Math.max(0, Math.min(region.x, image.naturalWidth));
    const y = Math.max(0, Math.min(region.y, image.naturalHeight));
    const width = Math.max(0, Math.min(region.width, image.naturalWidth - x));
    const height = Math.max(0, Math.min(region.height, image.naturalHeight - y));
    if (width > 0 && height > 0) context.fillRect(x, y, width, height);
  }
  return controlledPng(canvas);
}
