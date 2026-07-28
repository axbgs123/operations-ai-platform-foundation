import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import {
  confirmImport,
  previewTabularImport,
  updateImportMapping,
  updateImportRow,
} from "@/lib/import-api";

import { ImportReview } from "./import-review";


const preview = {
  id: "batch-1",
  workspace_id: "workspace-1",
  account_id: "account-1",
  platform: "douyin" as const,
  content_type: "video" as const,
  source_kind: "csv" as const,
  status: "preview" as const,
  recognition_status: null,
  recognition_error: null,
  provider_mode: "mock",
  region: null,
  file_name: "synthetic.csv",
  header_mappings: [
    {
      source_header: "标题",
      target_field: "title",
      confidence: 1,
      high_confidence: true,
    },
  ],
  summary: { new: 1, update: 0, suspected_duplicate: 0, failed: 1 },
  rows: [
    {
      id: "row-valid",
      row_number: 2,
      status: "new" as const,
      selected: false,
      raw_data: { 标题: "合成标题" },
      normalized_data: { title: "合成标题", metrics: { views: "100" } },
      errors: [],
      matched_content_id: null,
      dedupe_reason: null,
    },
    {
      id: "row-failed",
      row_number: 3,
      status: "failed" as const,
      selected: false,
      raw_data: { 标题: "" },
      normalized_data: { title: null, metrics: {} },
      errors: [{ field: "title", message: "title is required" }],
      matched_content_id: null,
      dedupe_reason: null,
    },
  ],
};

vi.mock("@/lib/import-api", () => ({
  confirmImport: vi.fn(),
  previewManualImport: vi.fn(),
  previewTabularImport: vi.fn(),
  updateImportMapping: vi.fn(),
  updateImportRow: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.setItem("workspace_csrf", "csrf-token");
  vi.mocked(previewTabularImport).mockResolvedValue(preview);
  vi.mocked(updateImportMapping).mockResolvedValue(preview);
  vi.mocked(updateImportRow).mockResolvedValue(preview);
  vi.mocked(confirmImport).mockResolvedValue({
    batch_id: "batch-1",
    content_ids: ["content-1"],
    snapshot_ids: ["snapshot-1"],
    skipped_row_ids: [],
  });
});

afterEach(cleanup);

test("renders file and manual staging controls before any formal write", () => {
  render(
    <ImportReview
      accountId="account-1"
      platform="douyin"
      workspaceId="workspace-1"
    />,
  );

  expect(screen.getByRole("heading", { name: "运营数据暂存导入" })).toBeInTheDocument();
  expect(screen.getByLabelText("CSV 或 Excel 文件")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "手动录入一行" })).toBeInTheDocument();
  expect(screen.getByText("预览不会写入正式内容或指标快照")).toBeInTheDocument();
});

test("previews row states, applies high confidence mappings, corrects and confirms selection", async () => {
  render(
    <ImportReview
      accountId="account-1"
      platform="douyin"
      workspaceId="workspace-1"
    />,
  );
  const file = new File(["标题,播放量\n合成标题,100"], "synthetic.csv", {
    type: "text/csv",
  });
  fireEvent.change(screen.getByLabelText("CSV 或 Excel 文件"), {
    target: { files: [file] },
  });
  fireEvent.click(screen.getByRole("button", { name: "生成暂存预览" }));

  expect(await screen.findByText("新增 1")).toBeInTheDocument();
  expect(screen.getByText("失败 1")).toBeInTheDocument();
  expect(screen.getByText("title is required")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "采用所有高置信度映射" }));
  await waitFor(() => {
    expect(updateImportMapping).toHaveBeenCalledWith(
      "batch-1",
      { 标题: "title" },
      "csrf-token",
    );
  });

  fireEvent.change(screen.getByLabelText("第 2 行标题"), {
    target: { value: "人工修正标题" },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存第 2 行修正" }));
  await waitFor(() => {
    expect(updateImportRow).toHaveBeenCalledWith(
      "batch-1",
      "row-valid",
      { title: "人工修正标题" },
      "csrf-token",
    );
  });

  expect(screen.getByLabelText("选择第 3 行")).toBeDisabled();
  fireEvent.click(screen.getByLabelText("选择第 2 行"));
  fireEvent.click(screen.getByRole("button", { name: "人工确认并写入正式数据" }));
  await waitFor(() => {
    expect(confirmImport).toHaveBeenCalledWith(
      "batch-1",
      ["row-valid"],
      "csrf-token",
    );
  });
  expect(await screen.findByText("已写入 1 条内容和 1 条指标快照")).toBeInTheDocument();
});
