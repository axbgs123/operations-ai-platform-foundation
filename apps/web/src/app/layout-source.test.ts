import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { expect, test } from "vitest";

function relativeLuminance(hex: string): number {
  const channels = hex
    .slice(1)
    .match(/.{2}/g)
    ?.map((channel) => Number.parseInt(channel, 16) / 255);
  if (!channels || channels.length !== 3) {
    throw new Error(`invalid hex color: ${hex}`);
  }
  const [red, green, blue] = channels.map((channel) =>
    channel <= 0.04045
      ? channel / 12.92
      : ((channel + 0.055) / 1.055) ** 2.4,
  );
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

function contrastRatio(foreground: string, background: string): number {
  const luminances = [
    relativeLuminance(foreground),
    relativeLuminance(background),
  ].sort((left, right) => right - left);
  return (luminances[0] + 0.05) / (luminances[1] + 0.05);
}


test("root layout does not require network fonts during local development", () => {
  const layoutPath = resolve(process.cwd(), "src/app/layout.tsx");
  const source = readFileSync(layoutPath, "utf8");

  expect(source).not.toContain("next/font/google");
});

test("global styles define the fixed light workbench tokens and accessibility safeguards", () => {
  const stylesPath = resolve(process.cwd(), "src/app/globals.css");
  const source = readFileSync(stylesPath, "utf8");

  for (const token of [
    "--canvas: #f5f7fb",
    "--surface: #ffffff",
    "--text-primary: #1b2430",
    "--text-secondary: #687482",
    "--border: #e2e6ec",
    "--brand: #6d55dc",
    "--success:",
    "--warning:",
    "--danger:",
    "--info:",
  ]) {
    expect(source.toLowerCase()).toContain(token);
  }
  expect(source).not.toContain("prefers-color-scheme: dark");
  expect(source).toContain(":focus-visible");
  expect(source).toContain("prefers-reduced-motion: reduce");
  expect(source).toContain("-apple-system");
});

test("secondary text meets the WCAG AA contrast target on a white surface", () => {
  const stylesPath = resolve(process.cwd(), "src/app/globals.css");
  const source = readFileSync(stylesPath, "utf8");
  const secondary = source.match(/--text-secondary:\s*(#[0-9a-f]{6})/i)?.[1];
  const surface = source.match(/--surface:\s*(#[0-9a-f]{6})/i)?.[1];

  expect(secondary).toBeDefined();
  expect(surface).toBeDefined();
  expect(contrastRatio(secondary!, surface!)).toBeGreaterThanOrEqual(4.5);
});
