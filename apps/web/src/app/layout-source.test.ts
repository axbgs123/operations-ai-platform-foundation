import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { expect, test } from "vitest";


test("root layout does not require network fonts during local development", () => {
  const layoutPath = resolve(process.cwd(), "src/app/layout.tsx");
  const source = readFileSync(layoutPath, "utf8");

  expect(source).not.toContain("next/font/google");
});
