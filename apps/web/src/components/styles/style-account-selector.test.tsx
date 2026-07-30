import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { StyleAccountSelector } from "./style-account-selector";

const accounts = [
  { account_id: "dy-account", platform: "douyin" as const, name: "抖音账号" },
  {
    account_id: "xhs-account",
    platform: "xiaohongshu" as const,
    name: "小红书账号",
  },
];

test("requires one platform account and never merges style profiles", () => {
  render(
    <StyleAccountSelector
      accounts={accounts}
      workspaceId="workspace-1"
    />,
  );

  expect(screen.getByRole("heading", { name: "账号风格" })).toBeVisible();
  expect(screen.getByText("风格档案始终固定到单个平台账号，不提供全部账号合并视图。")).toBeVisible();
  expect(screen.getByRole("link", { name: "查看抖音账号风格" })).toHaveAttribute(
    "href",
    "/workspaces/workspace-1/styles/dy-account?platform=douyin&account=dy-account",
  );
  expect(screen.getByRole("link", { name: "查看小红书账号风格" })).toHaveAttribute(
    "href",
    "/workspaces/workspace-1/styles/xhs-account?platform=xiaohongshu&account=xhs-account",
  );
  expect(screen.getAllByText("当前版本：进入账号查看")).toHaveLength(2);
});
