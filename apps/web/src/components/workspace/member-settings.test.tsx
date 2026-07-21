import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { MemberSettings } from "./member-settings";


test("renders independent invite controls and role guidance", () => {
  render(<MemberSettings workspaceId="workspace-1" />);

  expect(screen.getByRole("heading", { name: "成员与邀请码" })).toBeInTheDocument();
  expect(screen.getByLabelText("成员角色")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "生成独立邀请码" })).toBeInTheDocument();
  expect(screen.getByText(/一人一码/)).toBeInTheDocument();
});
