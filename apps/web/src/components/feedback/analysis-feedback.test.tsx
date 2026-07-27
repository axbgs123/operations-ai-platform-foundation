import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { AnalysisFeedback } from "./analysis-feedback";

afterEach(cleanup);

describe("AnalysisFeedback", () => {
  test("shows submitting, selected success, and permits an append-only change", async () => {
    let release: (() => void) | undefined;
    const submit = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          release = resolve;
        }),
    );
    render(<AnalysisFeedback onSubmit={submit} />);

    fireEvent.click(screen.getByRole("button", { name: "有用" }));
    expect(screen.getByRole("button", { name: "提交中…" })).toBeDisabled();
    release?.();
    await waitFor(() => expect(screen.getByText("反馈已记录")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "有用" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    fireEvent.click(screen.getByRole("button", { name: "无用" }));
    release?.();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "无用" })).toHaveAttribute(
        "aria-pressed",
        "true",
      ),
    );
    expect(submit).toHaveBeenNthCalledWith(1, "useful");
    expect(submit).toHaveBeenNthCalledWith(2, "not_useful");
  });

  test("shows a safe retryable failure without collecting free text", async () => {
    const submit = vi.fn().mockRejectedValue(new Error("synthetic failure"));
    render(<AnalysisFeedback onSubmit={submit} />);
    fireEvent.click(screen.getByRole("button", { name: "无用" }));
    expect(await screen.findByText("反馈提交失败，请重试")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });
});
