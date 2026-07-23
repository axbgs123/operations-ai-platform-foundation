import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";

import { GenerationTaskStatus, TaskStatus } from "./task-status";


afterEach(cleanup);


test.each([
  ["queued", "等待执行"],
  ["running", "正在执行"],
  ["succeeded", "执行成功"],
  ["failed", "执行失败"],
  ["cancelled", "已取消"],
  ["retrying", "正在重试"],
] as const)("renders explainable label for %s", (status, label) => {
  render(<TaskStatus status={status} />);

  expect(screen.getByRole("status")).toHaveTextContent(label);
});


test("shows progress and permits cancellation only for active work", async () => {
  const user = userEvent.setup();
  const onCancel = vi.fn();

  render(
    <TaskStatus
      detail="正在执行事实复检"
      onCancel={onCancel}
      progress={45}
      status="running"
    />,
  );

  expect(screen.getByRole("progressbar")).toHaveAttribute(
    "aria-valuenow",
    "45",
  );
  expect(screen.getByText("正在执行事实复检")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "取消任务" }));
  expect(onCancel).toHaveBeenCalledOnce();
  expect(
    screen.queryByRole("button", { name: "重试任务" }),
  ).not.toBeInTheDocument();
});


test.each<GenerationTaskStatus>(["failed", "cancelled"])(
  "permits retry after %s and exposes stable error details",
  async (status) => {
    const user = userEvent.setup();
    const onRetry = vi.fn();

    render(
      <TaskStatus
        detail="请检查已确认事实后重试"
        errorCode="FACT_CONFLICT"
        onRetry={onRetry}
        status={status}
      />,
    );

    expect(screen.getByText("FACT_CONFLICT")).toBeInTheDocument();
    expect(screen.getByText("请检查已确认事实后重试")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重试任务" }));
    expect(onRetry).toHaveBeenCalledOnce();
    expect(
      screen.queryByRole("button", { name: "取消任务" }),
    ).not.toBeInTheDocument();
  },
);


test("does not expose task actions after success", () => {
  render(<TaskStatus status="succeeded" />);

  expect(
    screen.queryByRole("button", { name: "取消任务" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "重试任务" }),
  ).not.toBeInTheDocument();
});
