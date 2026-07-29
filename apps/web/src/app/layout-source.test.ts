import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { expect, test } from "vitest";


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
    "--text-secondary: #6f7b89",
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
