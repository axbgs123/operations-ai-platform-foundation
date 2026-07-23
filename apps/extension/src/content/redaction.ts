import type { Rect } from "./page-adapters/base";

export type PreviewImage = {
  imageData: string;
  maskedRegions: Rect[];
};

export const applyRectangularRedaction = (
  preview: PreviewImage,
  regions: Rect[],
): PreviewImage => ({
  imageData: `masked:${preview.imageData}`,
  maskedRegions: [...preview.maskedRegions, ...regions],
});
