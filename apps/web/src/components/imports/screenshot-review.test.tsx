import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import {
  confirmImport,
  readImportBatch,
  stageScreenshotRecognition,
  updateImportRow,
} from "@/lib/import-api";

import { ScreenshotReview } from "./screenshot-review";


const pending = {
  id: "batch-screenshot",
  workspace_id: "workspace-1",
  account_id: "account-1",
  platform: "douyin" as const,
  content_type: "video" as const,
  source_kind: "screenshot" as const,
  status: "preview" as const,
  recognition_status: "pending" as const,
  recognition_error: null,
  provider_mode: "mock",
  region: null,
  file_name: null,
  header_mappings: [],
  summary: { new: 0, update: 0, suspected_duplicate: 0, failed: 0 },
  rows: [],
};

const ready = {
  ...pending,
  recognition_status: "ready" as const,
  summary: { new: 1, update: 0, suspected_duplicate: 0, failed: 0 },
  rows: [
    {
      id: "row-screenshot",
      row_number: 1,
      status: "new" as const,
      selected: false,
      raw_data: {
        platform: "douyin",
        platform_confidence: 0.99,
        content_identifier: null,
        metric_candidates: [
          { key: "views", value: "12000", confidence: 0.98, region: {} },
          { key: "likes", value: "345", confidence: 0.42, region: {} },
        ],
      },
      normalized_data: {
        title: "合成截图标题",
        metrics: { views: "12000" },
        metric_confidences: { views: 0.98 },
      },
      errors: [],
      matched_content_id: null,
      dedupe_reason: null,
    },
  ],
};

vi.mock("@/lib/import-api", () => ({
  confirmImport: vi.fn(),
  readImportBatch: vi.fn(),
  stageScreenshotRecognition: vi.fn(),
  updateImportRow: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.setItem("workspace_csrf", "csrf-token");
  vi.mocked(stageScreenshotRecognition).mockResolvedValue(pending);
  vi.mocked(readImportBatch).mockResolvedValue(ready);
  vi.mocked(updateImportRow).mockResolvedValue(ready);
  vi.mocked(confirmImport).mockResolvedValue({
    batch_id: "batch-screenshot",
    content_ids: ["content-1"],
    snapshot_ids: ["snapshot-1"],
    skipped_row_ids: [],
  });
});

afterEach(cleanup);

test("stages, reviews low confidence fields, corrects, and explicitly confirms", async () => {
  render(
    <ScreenshotReview
      accountId="account-1"
      platform="douyin"
      workspaceId="workspace-1"
    />,
  );
  fireEvent.change(screen.getByLabelText("截图文件"), {
    target: {
      files: [new File(["synthetic"], "mock.png", { type: "image/png" })],
    },
  });
  fireEvent.change(screen.getByLabelText("截图对应标题"), {
    target: { value: "合成截图标题" },
  });
  fireEvent.change(screen.getByLabelText("截图对应发布时间"), {
    target: { value: "2026-07-20T10:00" },
  });
  fireEvent.change(screen.getByLabelText("截图数据时间"), {
    target: { value: "2026-07-21T10:00" },
  });
  fireEvent.click(screen.getByRole("button", { name: "上传并开始识别" }));

  expect(await screen.findByText("识别排队中")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "刷新识别结果" }));
  expect(
    await screen.findByText("识别完成，等待人工确认"),
  ).toBeInTheDocument();
  expect(screen.getByText("views：12000 · 98%")).toBeInTheDocument();
  expect(screen.getByText("likes：345 · 42%（未采用）")).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("补正 likes"), {
    target: { value: "345" },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存人工修正" }));
  await waitFor(() => {
    expect(updateImportRow).toHaveBeenCalledWith(
      "batch-screenshot",
      "row-screenshot",
      { metrics: { views: "12000", likes: "345" } },
      "csrf-token",
    );
  });

  fireEvent.click(screen.getByLabelText("选择识别结果"));
  fireEvent.click(
    screen.getByRole("button", { name: "人工确认截图识别结果" }),
  );
  await waitFor(() => {
    expect(confirmImport).toHaveBeenCalledWith(
      "batch-screenshot",
      ["row-screenshot"],
      "csrf-token",
    );
  });
});

test("shows recognized platform conflicts before confirmation", async () => {
  vi.mocked(stageScreenshotRecognition).mockResolvedValue({
    ...ready,
    summary: { new: 0, update: 0, suspected_duplicate: 0, failed: 1 },
    rows: [
      {
        ...ready.rows[0],
        status: "failed",
        errors: [
          {
            field: "platform",
            message: "recognized platform conflicts with selected account",
          },
        ],
      },
    ],
  });
  render(
    <ScreenshotReview
      accountId="account-1"
      platform="douyin"
      workspaceId="workspace-1"
    />,
  );
  fireEvent.change(screen.getByLabelText("截图文件"), {
    target: {
      files: [new File(["synthetic"], "mock.png", { type: "image/png" })],
    },
  });
  fireEvent.change(screen.getByLabelText("截图对应标题"), {
    target: { value: "合成截图标题" },
  });
  fireEvent.change(screen.getByLabelText("截图对应发布时间"), {
    target: { value: "2026-07-20T10:00" },
  });
  fireEvent.change(screen.getByLabelText("截图数据时间"), {
    target: { value: "2026-07-21T10:00" },
  });
  fireEvent.click(screen.getByRole("button", { name: "上传并开始识别" }));

  expect(
    await screen.findByText(
      "recognized platform conflicts with selected account",
    ),
  ).toBeInTheDocument();
  expect(screen.getByLabelText("选择识别结果")).toBeDisabled();
});
