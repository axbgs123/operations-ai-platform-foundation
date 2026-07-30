import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";

import { MemberSettings } from "./member-settings";

const members = [
  {
    id: "member-1",
    workspace_id: "workspace-1",
    display_name: "合成管理员",
    role: "admin",
    status: "active",
    last_access_at: null,
    last_access_status: "not_recorded",
    invite_status: "redeemed",
  },
] as const;

afterEach(cleanup);

test("admin sees secret-free member status while access time remains honest", () => {
  render(
    <MemberSettings
      fixture={[...members]}
      role="admin"
      workspaceId="workspace-1"
    />,
  );

  expect(screen.getByText("合成管理员")).toBeVisible();
  expect(screen.getByText(/最后访问：当前认证合同未记录/)).toBeVisible();
  expect(screen.getByText(/邀请码：已兑换/)).toBeVisible();
  expect(
    screen.getByRole("button", { name: "生成独立邀请码" }),
  ).toBeVisible();
  expect(document.body.textContent).not.toMatch(/hash|token|session/i);
});

test("editor and viewer never receive member mutation controls", () => {
  const { rerender } = render(
    <MemberSettings role="editor" workspaceId="workspace-1" />,
  );
  expect(screen.getByText("当前角色不可管理成员或邀请码。")).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "生成独立邀请码" }),
  ).not.toBeInTheDocument();

  rerender(<MemberSettings role="viewer" workspaceId="workspace-1" />);
  expect(
    screen.queryByRole("button", { name: "生成独立邀请码" }),
  ).not.toBeInTheDocument();
});
