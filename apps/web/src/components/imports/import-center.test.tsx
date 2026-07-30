import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import type { ImportHistoryData } from "@/lib/import-api";

import { ImportCenter } from "./import-center";


afterEach(cleanup);

const accounts = [
  { account_id: "dy-1", platform: "douyin", name: "抖音账号" },
  { account_id: "xhs-1", platform: "xiaohongshu", name: "小红书账号" },
] as const;

const history = {
  items: [
    {
      id: "batch-1",
      method: "screenshot",
      platform: "douyin",
      account_id: "dy-1",
      account_name: "抖音账号",
      status: "waiting_confirmation",
      counts: {
        new: 1,
        update: 0,
        suspected_duplicate: 0,
        failed: 1,
      },
      created_at: "2026-07-30T09:00:00+08:00",
      confirmed_at: null,
      operator_name: "编辑成员",
      safe_error_code: "LOW_CONFIDENCE_FIELDS",
      next_action: "review",
    },
  ],
  page: 1,
  page_size: 20,
  total: 1,
  pages: 1,
  platform: "douyin",
  account_id: "dy-1",
} as ImportHistoryData;

test("exposes four methods through one staged preview and confirmation flow", () => {
  const onMethodChange = vi.fn();
  render(
    <ImportCenter
      accountId="dy-1"
      accounts={[...accounts]}
      history={history}
      method={undefined}
      onMethodChange={onMethodChange}
      onScopeChange={vi.fn()}
      platform="douyin"
      role="editor"
      workspaceId="workspace-1"
    />,
  );

  for (const label of [
    "手动录入",
    "Excel / CSV",
    "截图识别",
    "Capture Extension",
  ]) {
    expect(screen.getByRole("button", { name: label })).toBeVisible();
  }
  expect(screen.getByLabelText("统一导入流程")).toHaveTextContent("选择来源");
  expect(screen.getByLabelText("统一导入流程")).toHaveTextContent("上传/采集");
  expect(screen.getByLabelText("统一导入流程")).toHaveTextContent("暂存预览");
  expect(screen.getByLabelText("统一导入流程")).toHaveTextContent("修正");
  expect(screen.getByLabelText("统一导入流程")).toHaveTextContent("确认入库");
  fireEvent.click(screen.getByRole("button", { name: "Excel / CSV" }));
  expect(onMethodChange).toHaveBeenCalledWith("tabular");
});

test("keeps history safe and makes complex mapping desktop-only on mobile", () => {
  render(
    <ImportCenter
      accountId="dy-1"
      accounts={[...accounts]}
      history={history}
      method="tabular"
      onMethodChange={vi.fn()}
      onScopeChange={vi.fn()}
      platform="douyin"
      role="editor"
      workspaceId="workspace-1"
    />,
  );

  expect(screen.getByText("此操作需要电脑端")).toBeVisible();
  expect(screen.getByRole("table", { name: "导入历史桌面列表" })).toBeVisible();
  expect(screen.getByRole("list", { name: "导入历史移动卡片" })).toHaveClass(
    "md:hidden",
  );
  expect(screen.getByText("LOW_CONFIDENCE_FIELDS")).toBeVisible();
  expect(document.body.textContent).not.toMatch(
    /Authorization|Bearer|Cookie|raw_data|截图正文/,
  );
});

test("viewer sees history but no upload, edit, or confirmation controls", () => {
  render(
    <ImportCenter
      accountId="dy-1"
      accounts={[...accounts]}
      history={history}
      method={undefined}
      onMethodChange={vi.fn()}
      onScopeChange={vi.fn()}
      platform="douyin"
      role="viewer"
      workspaceId="workspace-1"
    />,
  );

  expect(screen.getByText("当前操作不可用")).toBeVisible();
  expect(screen.getByText("导入历史")).toBeVisible();
  expect(screen.queryByRole("button", { name: "手动录入" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /确认/ })).not.toBeInTheDocument();
  expect(screen.queryByLabelText("CSV 或 Excel 文件")).not.toBeInTheDocument();
});

test("clears an account when the selected platform is incompatible", () => {
  const onScopeChange = vi.fn();
  render(
    <ImportCenter
      accountId="dy-1"
      accounts={[...accounts]}
      history={history}
      method={undefined}
      onMethodChange={vi.fn()}
      onScopeChange={onScopeChange}
      platform="douyin"
      role="admin"
      workspaceId="workspace-1"
    />,
  );

  fireEvent.change(screen.getByLabelText("导入平台"), {
    target: { value: "xiaohongshu" },
  });
  expect(onScopeChange).toHaveBeenCalledWith({
    platform: "xiaohongshu",
    accountId: undefined,
  });
});
