import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";

import { TrashCenter, type TrashFixture } from "./trash-center";

const fixture: TrashFixture = {
  policy: {
    strategy: "evidence",
    version: 3,
    retention_seconds: 604800,
    effective_at: "2026-07-29T08:00:00Z",
  },
  items: [
    {
      id: "trash-1",
      resource_id: "content-1",
      resource_type: "content",
      title: "合成内容安全摘要",
      platform: "douyin",
      account_name: "抖音合成账号",
      deleted_by: "member-1",
      deleted_at: "2026-07-29T08:00:00Z",
      scheduled_purge_at: "2099-07-29T08:00:00Z",
      deletion_reason: "用户整理",
      status: "recoverable",
      restored_at: null,
      evidence_hold_reason: "关联风控扫描证据",
    },
    {
      id: "trash-2",
      resource_id: "content-2",
      resource_type: "content",
      title: "已恢复内容",
      platform: "xiaohongshu",
      account_name: "小红书合成账号",
      deleted_by: "member-1",
      deleted_at: "2026-07-28T08:00:00Z",
      scheduled_purge_at: "2026-07-29T08:00:00Z",
      deletion_reason: null,
      status: "restored",
      restored_at: "2026-07-29T07:00:00Z",
      evidence_hold_reason: null,
    },
  ],
};

afterEach(cleanup);

test("shows content lifecycle and separates workspace deletion", () => {
  render(
    <TrashCenter
      evaluatedAt="2026-07-30T00:00:00Z"
      fixture={fixture}
      role="admin"
      workspaceId="ws-1"
    />,
  );

  expect(screen.getByText("可恢复")).toBeVisible();
  expect(screen.getByText("已恢复")).toBeVisible();
  expect(screen.getByText("Evidence 保留：关联风控扫描证据")).toBeVisible();
  expect(screen.queryByRole("button", { name: "删除工作区" })).not.toBeInTheDocument();
  expect(screen.getByText(/工作区删除位于设置的危险操作/)).toBeVisible();
});

test("viewer receives no restore or purge operation", () => {
  render(
    <TrashCenter
      evaluatedAt="2026-07-30T00:00:00Z"
      fixture={fixture}
      role="viewer"
      workspaceId="ws-1"
    />,
  );

  expect(screen.queryByRole("button", { name: "恢复内容" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "最终删除" })).not.toBeInTheDocument();
});
