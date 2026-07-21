import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { AccountConfigEditor } from "./account-config-editor";


test("renders reorderable priorities, custom weights, and restore action", () => {
  render(
    <AccountConfigEditor
      accountId="account-1"
      workspaceId="workspace-1"
      initialObjectives={["engagement", "conversion", "reach"]}
      initialWeights={{ likes: 0.7, comments: 0.3 }}
    />,
  );

  expect(screen.getByRole("heading", { name: "账号目标与指标权重" })).toBeInTheDocument();
  expect(screen.getByText("拖拽调整目标优先级")).toBeInTheDocument();
  expect(screen.getByLabelText("likes 权重")).toBeInTheDocument();
  expect(screen.getByLabelText("comments 权重")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "保存并创建新版本" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "一键恢复账号默认" })).toBeInTheDocument();
});
