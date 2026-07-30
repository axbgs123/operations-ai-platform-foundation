import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { WorkspaceSettings } from "./workspace-settings";

test("keeps workspace deletion separate and does not offer it to a viewer", () => {
  render(<WorkspaceSettings workspaceId="ws-1" />);

  for (const title of [
    "工作区概览",
    "成员与邀请码",
    "平台账号配置",
    "指标、目标与基准",
    "模型配置与预算",
    "保留策略",
    "危险操作",
  ]) {
    expect(screen.getByRole("heading", { name: title })).toBeVisible();
  }
  expect(screen.getByText(/工作区删除与普通内容回收站分离/)).toBeVisible();
  expect(screen.getByText("只有管理员可以发起工作区删除。")).toBeVisible();
  expect(
    screen.queryByRole("button", { name: /删除工作区/ }),
  ).not.toBeInTheDocument();
});

test("admin deletion starts with impact preview and cannot skip confirmations", () => {
  render(<WorkspaceSettings role="admin" workspaceId="ws-1" />);

  expect(
    screen.getByRole("button", { name: "第一步：查看删除影响" }),
  ).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "最终确认删除工作区" }),
  ).not.toBeInTheDocument();
});
