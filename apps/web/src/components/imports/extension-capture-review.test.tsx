import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ExtensionCaptureReview } from "./extension-capture-review";

describe("ExtensionCaptureReview", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            task_id: "task-1",
            workspace_id: "workspace-1",
            status: "succeeded",
            request_id: "request-1",
            review_url: "/review/task-1",
            expires_at: "2030-01-01T00:00:00Z",
            recognition: {
              metric_candidates: [{ key: "views", value: "1000", confidence: 0.96 }],
            },
            error: null,
            formal_snapshot_ids: [],
            provider_mode: "mock",
            region: null,
          }),
          { status: 200 },
        ),
      ),
    );
    sessionStorage.setItem("workspace_csrf", "csrf-token");
  });

  it("requires Web correction and confirmation before creating a formal snapshot", async () => {
    render(<ExtensionCaptureReview taskId="task-1" />);
    expect(await screen.findByText("扩展识别结果待确认")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("修正 views"), { target: { value: "1200" } });
    fireEvent.click(screen.getByRole("button", { name: "人工确认并写入快照" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    const second = vi.mocked(fetch).mock.calls[1];
    expect(second[0]).toContain("/v1/imports/capture-tasks/task-1/confirm");
    expect(second[1]?.headers).toMatchObject({ "X-CSRF-Token": "csrf-token" });
  });
});
