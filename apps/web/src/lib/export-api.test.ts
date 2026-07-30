import { afterEach, expect, test, vi } from "vitest";

import { readRetentionPolicy } from "./export-api";

afterEach(() => {
  vi.unstubAllGlobals();
});

test("treats a missing retention policy as an unconfigured workspace", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "retention policy not found" }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );

  await expect(readRetentionPolicy("workspace-new")).resolves.toBeNull();
});

test("does not hide other retention policy failures", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "permission denied" }), {
        status: 403,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );

  await expect(readRetentionPolicy("workspace-other")).rejects.toThrow(
    "permission denied",
  );
});
