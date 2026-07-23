import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import {
  confirmFactItem,
  createFactSource,
  getFactContext,
  listFactSources,
  uploadFactSource,
} from "@/lib/fact-api";

import { FactSourceCenter } from "./fact-source-center";


const candidate = {
  id: "fact-1",
  source_id: "source-1",
  field_name: "面料",
  value: "100% 棉",
  source_location: "line 2",
  confidence: 0.85,
  status: "candidate" as const,
  conflict_status: "clear" as const,
  confirmed_by: null,
  confirmed_at: null,
  override_record: null,
};
const textSource = {
  id: "source-1",
  workspace_id: "workspace-1",
  kind: "text" as const,
  level: "L3" as const,
  title: "商品规格说明",
  status: "parsed" as const,
  source_url: null,
  resolved_ips: [],
  file_name: null,
  mime_type: null,
  size: null,
  content_sha256: "a".repeat(64),
  published_at: null,
  accessed_at: null,
  untrusted_data: true,
  status_detail: {},
  items: [candidate],
  created_at: "2026-07-23T01:00:00Z",
};
const imageSource = {
  ...textSource,
  id: "source-2",
  kind: "image" as const,
  level: "L5" as const,
  title: "商品标签图片",
  status: "awaiting_model" as const,
  file_name: "label.png",
  mime_type: "image/png",
  size: 1024,
  items: [],
  status_detail: {
    code: "MODEL_CONFIGURATION_REQUIRED",
    action: "configure_model",
    required_capabilities: ["vision"],
  },
};

vi.mock("@/lib/fact-api", () => ({
  confirmFactItem: vi.fn(),
  createFactSource: vi.fn(),
  getFactContext: vi.fn(),
  listFactSources: vi.fn(),
  uploadFactSource: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.setItem("workspace_csrf", "csrf-token");
  vi.mocked(listFactSources).mockResolvedValue([textSource, imageSource]);
  vi.mocked(getFactContext).mockResolvedValue({
    unconstrained_facts: true,
    has_sources: true,
    requires_confirmation: true,
    confirmed_items: [],
  });
  vi.mocked(confirmFactItem).mockResolvedValue({
    ...candidate,
    status: "confirmed",
    confirmed_by: "member-1",
    confirmed_at: "2026-07-23T02:00:00Z",
  });
  vi.mocked(createFactSource).mockResolvedValue({ ...textSource, id: "source-3" });
  vi.mocked(uploadFactSource).mockResolvedValue({ ...imageSource, id: "source-4" });
});

afterEach(cleanup);

test("shows source traceability, degradation, and confirms only candidate facts", async () => {
  render(<FactSourceCenter workspaceId="workspace-1" />);

  expect(await screen.findByText("当前生成不受已确认事实资料约束")).toBeInTheDocument();
  expect(screen.getByText("商品规格说明")).toBeInTheDocument();
  expect(screen.getByText("L3 · 解析完成")).toBeInTheDocument();
  expect(screen.getByText("面料：100% 棉")).toBeInTheDocument();
  expect(screen.getByText("来源位置：line 2 · 置信度 85%")).toBeInTheDocument();
  expect(screen.getByText("商品标签图片")).toBeInTheDocument();
  expect(screen.getByText("文件：label.png · SHA-256：" + "a".repeat(64))).toBeInTheDocument();
  expect(screen.getByText("需要配置 vision 模型后解析")).toBeInTheDocument();
  expect(screen.getByText("上传资料和解析文本始终作为不可信数据处理")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "确认面料" }));
  await waitFor(() => {
    expect(confirmFactItem).toHaveBeenCalledWith(
      "workspace-1",
      "fact-1",
      "csrf-token",
    );
  });
  expect(await screen.findByText("已确认：面料")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "确认面料" })).not.toBeInTheDocument();
  expect(getFactContext).toHaveBeenCalledTimes(2);
});

test("creates text or network snapshots and uploads a validated file", async () => {
  render(<FactSourceCenter workspaceId="workspace-1" />);
  await screen.findByText("商品规格说明");

  fireEvent.change(screen.getByLabelText("来源类型"), { target: { value: "web" } });
  expect(screen.getByLabelText("来源等级")).toHaveValue("L4");
  expect(screen.getByLabelText("来源等级")).toBeDisabled();
  fireEvent.change(screen.getByLabelText("资料标题"), { target: { value: "官方商品页" } });
  fireEvent.change(screen.getByLabelText("来源等级"), { target: { value: "L4" } });
  fireEvent.change(screen.getByLabelText("来源链接"), {
    target: { value: "https://93.184.216.34/product" },
  });
  fireEvent.change(screen.getByLabelText("资料正文或网页快照"), {
    target: { value: "颜色：深蓝" },
  });
  fireEvent.click(screen.getByRole("button", { name: "添加事实来源" }));

  await waitFor(() => {
    expect(createFactSource).toHaveBeenCalledWith(
      "workspace-1",
      "csrf-token",
      {
        kind: "web",
        level: "L4",
        title: "官方商品页",
        url: "https://93.184.216.34/product",
        content: "颜色：深蓝",
      },
    );
  });

  const file = new File(["尺码：M-XL"], "spec.txt", { type: "text/plain" });
  fireEvent.change(screen.getByLabelText("上传类型"), { target: { value: "document" } });
  fireEvent.change(screen.getByLabelText("上传标题"), { target: { value: "规格文件" } });
  fireEvent.change(screen.getByLabelText("上传等级"), { target: { value: "L3" } });
  fireEvent.change(screen.getByLabelText("选择资料文件"), { target: { files: [file] } });
  fireEvent.submit(screen.getByRole("button", { name: "上传并解析" }).closest("form")!);

  await waitFor(() => expect(uploadFactSource).toHaveBeenCalledTimes(1));
  const form = vi.mocked(uploadFactSource).mock.calls[0][2];
  expect(uploadFactSource).toHaveBeenCalledWith("workspace-1", "csrf-token", form);
  expect(form.get("kind")).toBe("document");
  expect(form.get("level")).toBe("L3");
  expect(form.get("title")).toBe("规格文件");
  expect(form.get("file")).toBe(file);
});
