import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";

import {
  ExportBackupCenter,
  type ExportBackupFixture,
} from "./export-backup-center";

const fixture: ExportBackupFixture = {
  tasks: [
    {
      id: "export-1",
      kind: "csv",
      status: "succeeded",
      created_at: "2026-07-29T08:00:00Z",
      completed_at: "2026-07-29T08:01:00Z",
      download_expires_at: "2026-07-29T08:06:00Z",
      error_code: null,
      requested_by: "member-1",
      file_name: "contents.csv",
    },
  ],
  restorePreview: [
    { action: "create", record_type: "content", reason: "目标不存在" },
    { action: "overwrite", record_type: "account", reason: "明确允许覆盖" },
    { action: "skip", record_type: "metric", reason: "内容一致" },
    { action: "conflict", record_type: "fact", reason: "引用不兼容" },
  ],
};

afterEach(cleanup);

test("distinguishes every backup type, restore action and secret exclusion", () => {
  render(
    <ExportBackupCenter
      evaluatedAt="2026-07-30T00:00:00Z"
      fixture={fixture}
      role="admin"
      workspaceId="ws-1"
    />,
  );

  for (const label of [
    "CSV 内容与运营数据",
    "Markdown 单条分析报告",
    "JSON 轻量备份",
    "ZIP 完整备份",
    "JSON 恢复预览",
    "ZIP 完整恢复",
  ]) {
    expect(screen.getAllByText(label)[0]).toBeVisible();
  }
  for (const label of ["新增", "覆盖", "跳过", "冲突"]) {
    expect(screen.getByText(label)).toBeVisible();
  }
  expect(screen.getByText(/API Key及密文/)).toBeVisible();
  expect(screen.getByText(/Embedding和向量/)).toBeVisible();
  expect(screen.getByText(/下载地址已过期/)).toBeVisible();
  expect(screen.getByLabelText("内容 ID")).toBeVisible();
  expect(
    screen.getByRole("button", { name: "创建Markdown 单条分析报告" }),
  ).toBeDisabled();
  expect(screen.getByLabelText("选择 JSON 并生成预览")).toHaveAttribute(
    "accept",
    "application/json,.json",
  );
  expect(screen.getByLabelText("选择 ZIP 并生成预览")).toHaveAttribute(
    "accept",
    "application/zip,.zip",
  );
});

test("viewer sees task state but no export or restore write actions", () => {
  render(
    <ExportBackupCenter
      evaluatedAt="2026-07-30T00:00:00Z"
      fixture={fixture}
      role="viewer"
      workspaceId="ws-1"
    />,
  );

  expect(screen.getAllByText("CSV 内容与运营数据")[0]).toBeVisible();
  expect(screen.queryByRole("button", { name: /创建/ })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /确认恢复/ })).not.toBeInTheDocument();
});
