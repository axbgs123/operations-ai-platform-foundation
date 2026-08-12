import { beforeEach, describe, expect, test } from "vitest";

import {
  clearWorkspaceSessionRecovery,
  readWorkspaceSessionRecovery,
  restoreWorkspaceCsrf,
  writeWorkspaceSessionRecovery,
} from "./workspace-session-recovery";


const validRecord = {
  workspaceId: "019fee9a-cb94-79b3-a0f0-3d6116c33d1d",
  memberId: "019fee9a-cb95-70ab-8b01-123456789abc",
  csrfToken: "csrf-token-with-sufficient-length",
};

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});

describe("workspace session recovery", () => {
  test("round-trips a valid versioned recovery record", () => {
    writeWorkspaceSessionRecovery(localStorage, validRecord);

    expect(readWorkspaceSessionRecovery(localStorage)).toEqual({
      version: 1,
      ...validRecord,
    });
  });

  test.each([
    ["malformed JSON", "{"],
    ["an unknown version", JSON.stringify({ version: 2, ...validRecord })],
    [
      "a non-UUID workspace",
      JSON.stringify({ version: 1, ...validRecord, workspaceId: "workspace-1" }),
    ],
    [
      "a non-UUID member",
      JSON.stringify({ version: 1, ...validRecord, memberId: "member-1" }),
    ],
    [
      "a short CSRF token",
      JSON.stringify({ version: 1, ...validRecord, csrfToken: "short" }),
    ],
    [
      "an extra field",
      JSON.stringify({ version: 1, ...validRecord, displayName: "private" }),
    ],
  ])("rejects and removes %s", (_label, storedValue) => {
    localStorage.setItem(
      "operations-ai:workspace-session-recovery:v1",
      storedValue,
    );
    localStorage.setItem("unrelated", "keep");

    expect(readWorkspaceSessionRecovery(localStorage)).toBeNull();
    expect(
      localStorage.getItem("operations-ai:workspace-session-recovery:v1"),
    ).toBeNull();
    expect(localStorage.getItem("unrelated")).toBe("keep");
  });

  test("clears only the workspace recovery record", () => {
    writeWorkspaceSessionRecovery(localStorage, validRecord);
    localStorage.setItem("unrelated", "keep");

    clearWorkspaceSessionRecovery(localStorage);

    expect(readWorkspaceSessionRecovery(localStorage)).toBeNull();
    expect(localStorage.getItem("unrelated")).toBe("keep");
  });

  test("restores the current tab CSRF token", () => {
    restoreWorkspaceCsrf(sessionStorage, { version: 1, ...validRecord });

    expect(sessionStorage.getItem("workspace_csrf")).toBe(
      validRecord.csrfToken,
    );
  });
});
