import { cleanup, fireEvent, render as rtlRender, screen, waitFor } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { WorkspaceShell } from "@/components/workbench/workspace-shell";
import {
  confirmFactItem,
  createFactSource,
  getFactContext,
  listFactSources,
  uploadFactSource,
} from "@/lib/fact-api";

import { FactSourceCenter } from "./fact-source-center";

vi.mock("next/navigation", () => ({
  usePathname: () => "/workspaces/workspace-1/facts",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

const candidate = {
  id: "fact-1",
  source_id: "source-1",
  field_name: "面料",
  field_code: "fabric",
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

const shellContext = {
  workspace_id: "workspace-1",
  workspace_name: "运营工作区",
  member_id: "member-admin",
  member_display_name: "运营管理员",
  role: "admin" as const,
  accounts: [],
  failed_task_count: 0,
};

function renderInWorkspace(
  ui: ReactElement,
  role: "admin" | "editor" | "viewer" = "admin",
) {
  return rtlRender(ui, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <WorkspaceShell context={{ ...shellContext, role }}>
        {children}
      </WorkspaceShell>
    ),
  });
}

vi.mock("@/lib/fact-api", () => ({
  confirmFactItem: vi.fn(),
  createFactSource: vi.fn(),
  getFactContext: vi.fn(),
  listFactSources: vi.fn(),
  uploadFactSource: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  });
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

test("shows one easy visual-fact boundary without professional or static duplicates", async () => {
  renderInWorkspace(<FactSourceCenter workspaceId="workspace-1" />);

  expect(await screen.findByText(
    "保存商品、活动或选题中可以确认的事实，生成时用它减少写错和虚假宣传。",
  )).toBeVisible();
  expect(screen.getAllByText(
    "图片只能帮助识别可能出现的文字或外观，不能证明面料、价格、功效、认证等事实。",
  )).toHaveLength(1);
  expect(screen.queryByText(
    "L5 视觉推断不能升级为已验证事实，也不能单独支撑确定性生成声明。",
  )).not.toBeInTheDocument();
  expect(screen.queryByText(
    "视觉判断不能证明面料、价格、功效或认证。",
  )).not.toBeInTheDocument();
});

test("shows one professional visual-fact boundary without easy or static duplicates", async () => {
  localStorage.setItem("operations-ai:copy-mode:member-admin", "professional");
  renderInWorkspace(<FactSourceCenter workspaceId="workspace-1" />);

  expect(await screen.findAllByText(
    "L5 视觉推断不能升级为已验证事实，也不能单独支撑确定性生成声明。",
  )).toHaveLength(1);
  expect(screen.queryByText(
    "图片只能帮助识别可能出现的文字或外观，不能证明面料、价格、功效、认证等事实。",
  )).not.toBeInTheDocument();
  expect(screen.queryByText(
    "视觉判断不能证明面料、价格、功效或认证。",
  )).not.toBeInTheDocument();
  expect(document.body).toHaveTextContent("OCR");
});

test("shows source traceability, degradation, and confirms only candidate facts", async () => {
  renderInWorkspace(<FactSourceCenter workspaceId="workspace-1" />);

  expect(await screen.findByText("当前生成不受已确认事实资料约束")).toBeInTheDocument();
  expect(screen.getByText("商品规格说明")).toBeInTheDocument();
  expect(screen.getByText("L3 · 解析完成")).toBeInTheDocument();
  expect(screen.getByText("面料：100% 棉")).toBeInTheDocument();
  expect(screen.getByText("来源位置：line 2 · 判断可靠程度 85%")).toBeInTheDocument();
  expect(screen.getByText("商品标签图片")).toBeInTheDocument();
  expect(screen.getByText("文件：label.png · SHA-256：" + "a".repeat(64))).toBeInTheDocument();
  expect(screen.getByText("需要配置图片理解能力后解析")).toBeInTheDocument();
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
  renderInWorkspace(<FactSourceCenter workspaceId="workspace-1" />);
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

test("presents source and fact lists with all governed levels", async () => {
  renderInWorkspace(<FactSourceCenter workspaceId="workspace-1" />);

  expect(await screen.findByRole("heading", { name: "来源列表" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "事实清单" })).toBeVisible();
  expect(screen.getByText("L1：权威结构化资料")).toBeVisible();
  expect(screen.getByText("L2：用户明确填写并确认")).toBeVisible();
  expect(screen.getByText("L3：文档或图片文字提取后人工确认")).toBeVisible();
  expect(screen.getByText("L4：外部网页候选，具体参数仍需人工确认")).toBeVisible();
  expect(screen.getByText("L5：视觉模型推测，只能作为候选提示")).toBeVisible();
  expect(screen.getByText("用户确认状态：未确认")).toBeVisible();
  expect(screen.getByText("系统验证状态：未验证")).toBeVisible();
  expect(screen.getByText("当前是否可用于生成：否")).toBeVisible();
  expect(screen.getByText("生效范围：工作区通用（当前记录未提供更细范围）")).toBeVisible();
});

test("labels L5 visual inference as non-deterministic and blocks confirmation", async () => {
  vi.mocked(listFactSources).mockResolvedValue([{
    ...imageSource,
    status: "parsed",
    status_detail: {},
    items: [{
      ...candidate,
      id: "fact-l5",
      source_id: "source-2",
      status: "candidate",
    }],
  }]);
  renderInWorkspace(<FactSourceCenter workspaceId="workspace-1" />);

  expect(await screen.findByText("禁止仅凭视觉推测写入确定性文案")).toBeVisible();
  expect(screen.getByText("面料、成分、价格、尺码、功效、认证、产地和安全承诺不得仅凭视觉推断。")).toBeVisible();
  expect(screen.getByText("当前是否可用于生成：否")).toBeVisible();
  expect(screen.queryByRole("button", { name: "确认面料" })).not.toBeInTheDocument();
});

test("does not pretend that automatic web search is configured", async () => {
  renderInWorkspace(<FactSourceCenter workspaceId="workspace-1" />);
  expect(
    await screen.findByText("当前版本支持添加网页来源，自动联网检索尚未配置"),
  ).toBeVisible();
  expect(screen.getByText("网页正文始终是不可信数据；localhost、内网和云元数据地址会被服务端拒绝。")).toBeVisible();
  expect(screen.queryByRole("button", { name: /联网搜索/ })).not.toBeInTheDocument();
});

test("viewer has read-only fact access", async () => {
  renderInWorkspace(
    <FactSourceCenter role="viewer" workspaceId="workspace-1" />,
    "viewer",
  );
  expect(await screen.findByRole("heading", { name: "事实清单" })).toBeVisible();
  expect(screen.queryByRole("button", { name: "添加事实来源" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "上传并解析" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "确认面料" })).not.toBeInTheDocument();
  expect(screen.getByText("建议先做").closest("p")).not.toHaveTextContent(
    /确认候选|确认新版本|添加来源|开始生成/,
  );
  expect(screen.getByText("查看者可查看事实与冲突状态，不能添加来源或确认候选")).toBeVisible();
});

test("viewer empty guidance only supports reading and contacting an authorized member", async () => {
  vi.mocked(listFactSources).mockResolvedValueOnce([]);
  vi.mocked(getFactContext).mockResolvedValueOnce({
    unconstrained_facts: true,
    has_sources: false,
    requires_confirmation: false,
    confirmed_items: [],
  });
  renderInWorkspace(
    <FactSourceCenter role="viewer" workspaceId="workspace-1" />,
    "viewer",
  );

  expect(await screen.findByText(
    "这里还没有事实来源；需要补充资料时，请联系管理员或编辑者。",
  )).toBeVisible();
  expect(screen.getByText(
    "这里还没有候选事实；需要补充或确认时，请联系管理员或编辑者。",
  )).toBeVisible();
  expect(document.body).not.toHaveTextContent("下一步：添加文字、网页、文档或图片资料");
});

test("uses readable source and fact cards at 390px", async () => {
  renderInWorkspace(<FactSourceCenter workspaceId="workspace-1" />);
  expect(await screen.findByTestId("fact-source-cards")).toHaveClass("grid-cols-1");
  expect(screen.getByTestId("fact-item-cards")).toHaveClass("grid-cols-1");
});
