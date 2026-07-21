import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import EnterPage from "./page";


test("renders invite code and display name inputs", () => {
  render(<EnterPage />);

  expect(
    screen.getByRole("heading", { name: "使用邀请码进入工作区" }),
  ).toBeInTheDocument();
  expect(screen.getByLabelText("邀请码")).toBeInTheDocument();
  expect(screen.getByLabelText("显示名称")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "进入工作区" })).toBeInTheDocument();
});
