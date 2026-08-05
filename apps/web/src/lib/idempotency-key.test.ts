import { afterEach, expect, test, vi } from "vitest";

import { createIdempotencyKey } from "./idempotency-key";

afterEach(() => {
  vi.unstubAllGlobals();
});

test("creates a secure key when randomUUID is unavailable", () => {
  vi.stubGlobal("crypto", {
    getRandomValues: (bytes: Uint8Array) => {
      bytes.forEach((_, index) => {
        bytes[index] = index;
      });
      return bytes;
    },
  });

  expect(createIdempotencyKey("agent-plan")).toBe(
    "agent-plan-000102030405060708090a0b0c0d0e0f",
  );
});

test("uses randomUUID when the browser provides it", () => {
  vi.stubGlobal("crypto", {
    randomUUID: () => "123e4567-e89b-12d3-a456-426614174000",
  });

  expect(createIdempotencyKey("agent-plan")).toBe(
    "agent-plan-123e4567-e89b-12d3-a456-426614174000",
  );
});
