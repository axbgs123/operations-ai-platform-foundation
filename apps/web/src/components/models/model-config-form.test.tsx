import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { WorkspaceShell } from "@/components/workbench/workspace-shell";
import { ModelConfigForm } from "./model-config-form";

vi.mock("next/navigation", () => ({
  usePathname: () => "/workspaces/workspace-1/settings/models",
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

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
  return render(ui, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <WorkspaceShell context={{ ...shellContext, role }}>
        {children}
      </WorkspaceShell>
    ),
  });
}


const { listModelConfigs, saveModelConfig, updateModelConfigStatus } = vi.hoisted(() => ({
  listModelConfigs: vi.fn(),
  saveModelConfig: vi.fn(),
  updateModelConfigStatus: vi.fn(),
}));
const { createModelValidation, verifyNativeWebSearch } = vi.hoisted(() => ({
  createModelValidation: vi.fn(),
  verifyNativeWebSearch: vi.fn(),
}));

vi.mock("@/lib/model-api", () => ({
  getModelCatalog: vi.fn(async () => ({
    provider: "qianwen",
    regions: ["ap-southeast-1", "cn-beijing"],
    models: [
      {
        model_id: "qwen3.5-plus-2026-04-20",
        capability: "text",
        contract_version: "qianwen-chat-json-v1",
        experimental: true,
        upstream_snapshot_immutable: true,
      },
      {
        model_id: "text-embedding-v4",
        capability: "embedding",
        contract_version: "qianwen-text-embedding-v4-d1024-v1",
        experimental: true,
        upstream_snapshot_immutable: false,
      },
    ],
  })),
  listModelConfigs,
  saveModelConfig,
  updateModelConfigStatus,
  createModelValidation,
  verifyNativeWebSearch,
}));

beforeEach(() => {
  localStorage.clear();
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: vi.fn().mockReturnValue({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  });
  saveModelConfig.mockReset();
  listModelConfigs.mockReset();
  listModelConfigs.mockResolvedValue([]);
  updateModelConfigStatus.mockReset();
  saveModelConfig.mockResolvedValue({
    id: "config-1",
    provider: "qianwen",
    model_id: "qwen3.5-plus-2026-04-20",
    capability: "text",
    region: "cn-beijing",
    status: "experimental",
    experimental: true,
    credential_configured: true,
    credential_updated_at: "2026-07-29T00:00:00Z",
    configuration_version: "config-v1",
    contract_version: "qianwen-chat-json-v1",
    last_validation_status: "not_run",
    last_validated_at: null,
    safe_error_code: "explicit_user_authorization_missing",
    native_web_search_status: "unknown",
    native_web_search_checked_at: null,
    native_web_search_contract_version: null,
    native_web_search_safe_error_code: null,
  });
  updateModelConfigStatus.mockImplementation(
    async (
      _workspaceId: string,
      _configId: string,
      status: "experimental" | "incompatible",
    ) => ({
      id: "config-1",
      provider: "qianwen",
      model_id: "qwen3.5-plus-2026-04-20",
      capability: "text",
      region: "cn-beijing",
      status,
      experimental: status === "experimental",
      credential_configured: true,
      credential_updated_at: "2026-07-29T00:00:00Z",
      configuration_version: `config-${status}`,
      contract_version: "qianwen-chat-json-v1",
      last_validation_status: "not_run",
      last_validated_at: null,
      safe_error_code: "explicit_user_authorization_missing",
    }),
  );
  createModelValidation.mockReset();
  createModelValidation.mockResolvedValue({
    result: "not_run",
    safe_error_code: "explicit_user_authorization_missing",
  });
  verifyNativeWebSearch.mockReset();
  verifyNativeWebSearch.mockResolvedValue({
    model_config_id: "config-1",
    status: "supported",
    checked_at: "2026-08-13T00:00:00Z",
    contract_version: "qianwen-responses-native-search-v1",
    source_count: 2,
    source_hosts: ["help.aliyun.com"],
    safe_error_code: null,
    real_model_invoked: true,
  });
  sessionStorage.setItem("workspace_csrf", "csrf-token");
});

afterEach(cleanup);

test("admin keeps the fixed catalog flow and clears the key after save", async () => {
  localStorage.setItem("operations-ai:copy-mode:member-admin", "professional");
  renderInWorkspace(<ModelConfigForm role="admin" workspaceId="workspace-1" />);

  expect(await screen.findByText("AI 模型连接")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "千问官方" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(screen.getByLabelText("精确模型")).toHaveValue(
    "qwen3.5-plus-2026-04-20",
  );
  expect(screen.queryByLabelText(/base_url/i)).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Provider Workspace ID")).not.toBeInTheDocument();
  expect(screen.getByText("experimental")).toBeInTheDocument();
  expect(screen.getByText(/千问 AI 平台官方固定接口/)).toBeInTheDocument();
  expect(screen.getByText(/调用可能产生费用/)).toBeInTheDocument();
  expect(screen.queryByText("工作区用量政策（UTC 日界线）")).not.toBeInTheDocument();

  const key = screen.getByLabelText("API Key");
  expect(key).toHaveAttribute("autocomplete", "new-password");
  fireEvent.change(key, { target: { value: "synthetic-one-time-key" } });
  fireEvent.click(screen.getByRole("button", { name: "保存或替换密钥" }));

  await waitFor(() => expect(saveModelConfig).toHaveBeenCalledOnce());
  expect(saveModelConfig).toHaveBeenCalledWith(
    "workspace-1",
    "csrf-token",
    expect.objectContaining({
      provider: "qianwen",
      model_id: "qwen3.5-plus-2026-04-20",
      region: "cn-beijing",
      provider_workspace_id: null,
      api_key: "synthetic-one-time-key",
    }),
  );
  expect(key).toHaveValue("");
  expect(
    screen.getByRole("button", { name: "测试连接（不调用模型）" }),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "禁用配置" }));
  await waitFor(() =>
    expect(updateModelConfigStatus).toHaveBeenCalledWith(
      "workspace-1",
      "config-1",
      "incompatible",
      "csrf-token",
    ),
  );

});

test("viewer receives safe status without credential controls", async () => {
  renderInWorkspace(
    <ModelConfigForm role="viewer" workspaceId="workspace-1" />,
    "viewer",
  );

  expect(await screen.findByText("AI 模型连接")).toBeInTheDocument();
  expect(screen.getByText(
    "选择千问官方服务，或接入团队自己的兼容文本模型；保存后先测试连接。",
  )).toBeVisible();
  expect(screen.queryByLabelText("API Key")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "保存或替换密钥" }),
  ).not.toBeInTheDocument();
  expect(screen.getByText(/只读状态/)).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "保存用量政策" }),
  ).not.toBeInTheDocument();
});

test("easy mode explains secret storage, real provider cost, and trial status", async () => {
  renderInWorkspace(<ModelConfigForm role="admin" workspaceId="workspace-1" />);

  expect(await screen.findByText(
    "选择千问官方服务，或接入团队自己的兼容文本模型；保存后先测试连接。",
  )).toBeVisible();
  expect(screen.getByText(
    "密钥保存后不会再次显示；更换密钥需要重新输入。",
  )).toBeVisible();
  expect(screen.getByText(
    "可以使用千问官方服务，也可以接入支持 OpenAI 格式的文本模型。连接测试不会发送生成内容。",
  )).toBeVisible();
  expect(screen.getByText(
    "试用状态，真实效果和费用尚未完成验收",
  )).toBeVisible();
  expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  expect(screen.getByRole("button", { name: "千问官方" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(screen.getByLabelText("模型服务密钥")).toHaveAttribute("type", "password");
  expect(screen.queryByLabelText("Provider")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("API Key")).not.toBeInTheDocument();
  expect(screen.getByRole("option", { name: "文本生成模型" })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "资料检索模型" })).toBeInTheDocument();
  expect(document.body.textContent).not.toMatch(
    /\b(?:Provider|Embedding|Mock|API Key|not_run)\b|qwen3\.5-plus|text-embedding-v4/,
  );
});

test("uses the shared light form tokens for model credentials", async () => {
  const { container } = renderInWorkspace(
    <ModelConfigForm role="admin" workspaceId="workspace-1" />,
  );

  const model = await screen.findByLabelText("模型能力");
  expect(model).toHaveClass(
    "border-[var(--border)]",
    "bg-[var(--surface)]",
    "text-[var(--text-primary)]",
    "disabled:bg-slate-100",
    "disabled:text-[var(--text-secondary)]",
  );

  const key = screen.getByLabelText("模型服务密钥");
  expect(key).toHaveClass(
    "border-[var(--border)]",
    "bg-[var(--surface)]",
    "text-[var(--text-primary)]",
    "placeholder:text-[var(--text-secondary)]",
  );

  expect(container.querySelectorAll(
    '[class*="bg-slate-950"], [class*="bg-slate-900"]',
  )).toHaveLength(0);
});

test("easy mode translates loaded model and validation states without exposing safe codes", async () => {
  listModelConfigs.mockResolvedValueOnce([
    {
      id: "config-loaded-1",
      provider: "qianwen",
      model_id: "qwen3.5-plus-2026-04-20",
      capability: "text",
      region: "cn-beijing",
      status: "experimental",
      experimental: true,
      credential_configured: true,
      credential_updated_at: "2026-07-29T00:00:00Z",
      configuration_version: "config-loaded-v1",
      contract_version: "qianwen-chat-json-v1",
      last_validation_status: "not_run",
      last_validated_at: null,
      safe_error_code: "explicit_user_authorization_missing",
    },
    {
      id: "config-loaded-2",
      provider: "qianwen",
      model_id: "text-embedding-v4",
      capability: "embedding",
      region: "cn-beijing",
      status: "incompatible",
      experimental: false,
      credential_configured: true,
      credential_updated_at: "2026-07-29T00:00:00Z",
      configuration_version: "config-loaded-v2",
      contract_version: "qianwen-text-embedding-v4-d1024-v1",
      last_validation_status: "failed",
      last_validated_at: "2026-07-29T00:01:00Z",
      safe_error_code: "provider_outcome_unknown",
    },
  ]);

  renderInWorkspace(<ModelConfigForm role="admin" workspaceId="workspace-1" />);

  expect(await screen.findByText("连接状态：尚未测试连接")).toBeVisible();
  expect(screen.getByText("连接提示：尚未执行连接测试")).toBeVisible();
  expect(screen.getByText("当前配置不可用")).toBeVisible();
  expect(screen.getByText("连接状态：连接未通过")).toBeVisible();
  expect(screen.getByText(
    "连接提示：模型服务结果暂时无法确认，请勿直接重复提交",
  )).toBeVisible();
  expect(screen.queryByText("not_run")).not.toBeInTheDocument();
  expect(screen.queryByText(/explicit_user_authorization_missing/)).not.toBeInTheDocument();
  expect(screen.queryByText(/provider_outcome_unknown/)).not.toBeInTheDocument();
});

test("professional mode preserves loaded model states and safe error codes", async () => {
  localStorage.setItem("operations-ai:copy-mode:member-admin", "professional");
  listModelConfigs.mockResolvedValueOnce([
    {
      id: "config-loaded-1",
      provider: "qianwen",
      model_id: "qwen3.5-plus-2026-04-20",
      capability: "text",
      region: "cn-beijing",
      status: "experimental",
      experimental: true,
      credential_configured: true,
      credential_updated_at: "2026-07-29T00:00:00Z",
      configuration_version: "config-loaded-v1",
      contract_version: "qianwen-chat-json-v1",
      last_validation_status: "not_run",
      last_validated_at: null,
      safe_error_code: "explicit_user_authorization_missing",
    },
  ]);

  renderInWorkspace(<ModelConfigForm role="admin" workspaceId="workspace-1" />);

  expect(await screen.findByText("Connection status：not_run")).toBeVisible();
  expect(screen.getByText("状态码：explicit_user_authorization_missing")).toBeVisible();
  expect(screen.getAllByText("experimental")).toHaveLength(2);
  expect(screen.getByRole("button", { name: "千问官方" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

test("easy mode translates provider post-actions and uncertain validation outcomes", async () => {
  createModelValidation.mockResolvedValueOnce({
    result: "not_run",
    safe_error_code: "provider_outcome_unknown",
  });
  renderInWorkspace(<ModelConfigForm role="admin" workspaceId="workspace-1" />);

  const key = await screen.findByLabelText("模型服务密钥");
  fireEvent.change(key, { target: { value: "synthetic-one-time-key" } });
  fireEvent.click(screen.getByRole("button", { name: "保存或替换密钥" }));
  await screen.findByRole("button", { name: "测试连接（不调用模型）" });

  fireEvent.click(screen.getByRole("button", { name: "测试连接（不调用模型）" }));
  expect(await screen.findByText(
    "未运行：模型服务结果暂时无法确认，请勿直接重复提交",
  )).toBeVisible();

  fireEvent.click(screen.getByRole("button", { name: "禁用配置" }));
  expect(await screen.findByText(
    "配置已禁用；新任务不会调用该模型服务",
  )).toBeVisible();
});

test("connection test explains successful authentication without claiming a model call", async () => {
  createModelValidation.mockResolvedValueOnce({
    result: "passed",
    safe_error_code: null,
  });
  renderInWorkspace(<ModelConfigForm role="admin" workspaceId="workspace-1" />);

  const key = await screen.findByLabelText("模型服务密钥");
  fireEvent.change(key, { target: { value: "synthetic-one-time-key" } });
  fireEvent.click(screen.getByRole("button", { name: "保存或替换密钥" }));
  const testConnection = await screen.findByRole("button", {
    name: "测试连接（不调用模型）",
  });

  fireEvent.click(testConnection);

  expect(await screen.findByText(
    "连接成功：模型服务密钥与千问官方接口可以正常通信；尚未调用具体模型。",
  )).toBeVisible();
});

test("admin explicitly confirms a real native web search call", async () => {
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
  listModelConfigs.mockResolvedValueOnce([
    {
      id: "config-native-search",
      provider: "qianwen",
      model_id: "qwen3.5-plus-2026-04-20",
      capability: "text",
      region: "cn-beijing",
      status: "experimental",
      experimental: true,
      credential_configured: true,
      credential_updated_at: "2026-08-13T00:00:00Z",
      configuration_version: "config-v1",
      contract_version: "qianwen-chat-json-v1",
      last_validation_status: "passed",
      last_validated_at: "2026-08-13T00:00:00Z",
      safe_error_code: null,
      native_web_search_status: "unknown",
      native_web_search_checked_at: null,
      native_web_search_contract_version: null,
      native_web_search_safe_error_code: null,
    },
  ]);
  renderInWorkspace(<ModelConfigForm role="admin" workspaceId="workspace-1" />);

  const button = await screen.findByRole("button", {
    name: "测试模型联网（会真实调用）",
  });
  fireEvent.click(button);

  expect(confirm).toHaveBeenCalledWith(
    "这会真实调用一次模型自带的联网搜索，费用由你的模型供应商收取。是否继续？",
  );
  await waitFor(() => expect(verifyNativeWebSearch).toHaveBeenCalledWith(
    "workspace-1",
    "config-native-search",
    "csrf-token",
  ));
  expect(await screen.findByText(
    "模型联网可用：已收到 2 个可验证来源。",
  )).toBeVisible();
  expect(screen.getByText("模型联网：可用")).toBeVisible();
  confirm.mockRestore();
});

test("admin can configure and test a self-hosted compatible text model", async () => {
  saveModelConfig.mockResolvedValueOnce({
    id: "config-compatible-1",
    provider: "openai_compatible",
    display_name: "团队文本模型",
    endpoint_host: "models.example.com",
    model_id: "team-chat-v1",
    capability: "text",
    region: null,
    status: "community",
    experimental: false,
    credential_configured: true,
    credential_updated_at: "2026-08-12T00:00:00Z",
    configuration_version: "compatible-v1",
    contract_version: "openai-compatible-chat-json-v1",
    last_validation_status: "not_run",
    last_validated_at: null,
    safe_error_code: "explicit_user_authorization_missing",
  });
  createModelValidation.mockResolvedValueOnce({
    result: "passed",
    safe_error_code: null,
  });
  renderInWorkspace(<ModelConfigForm role="admin" workspaceId="workspace-1" />);

  await screen.findByText("AI 模型连接");
  fireEvent.click(screen.getByRole("button", { name: "OpenAI 兼容" }));
  expect(screen.getByLabelText("配置名称")).toBeVisible();
  expect(screen.getByLabelText("服务地址")).toBeVisible();
  expect(screen.getByLabelText("模型名称")).toBeVisible();
  expect(screen.getByText("费用由模型供应商结算，平台只限制调用次数和文字量。")).toBeVisible();
  expect(document.body.textContent).not.toMatch(/base_url|provider_workspace_id/);

  fireEvent.change(screen.getByLabelText("配置名称"), {
    target: { value: "团队文本模型" },
  });
  fireEvent.change(screen.getByLabelText("服务地址"), {
    target: { value: "https://models.example.com/v1" },
  });
  fireEvent.change(screen.getByLabelText("模型名称"), {
    target: { value: "team-chat-v1" },
  });
  const key = screen.getByLabelText("模型服务密钥");
  fireEvent.change(key, { target: { value: "synthetic-compatible-key" } });
  fireEvent.click(screen.getByRole("button", { name: "保存兼容模型配置" }));

  await waitFor(() => expect(saveModelConfig).toHaveBeenCalledWith(
    "workspace-1",
    "csrf-token",
    expect.objectContaining({
      provider: "openai_compatible",
      display_name: "团队文本模型",
      base_url: "https://models.example.com/v1",
      model_id: "team-chat-v1",
      capabilities: ["text"],
      status: "community",
      api_key: "synthetic-compatible-key",
    }),
  ));
  expect(key).toHaveValue("");
  fireEvent.click(screen.getByRole("button", { name: "测试连接（不调用模型）" }));
  await waitFor(() => expect(createModelValidation).toHaveBeenCalledWith(
    "workspace-1",
    "csrf-token",
    expect.objectContaining({ region: "provider-managed" }),
  ));
  expect(await screen.findByText(
    "连接成功：密钥、服务地址和模型名称均可用；尚未发送生成内容。",
  )).toBeVisible();
});

test("admin can configure the official GLM-5.3-Flash preset with only an API key", async () => {
  saveModelConfig.mockResolvedValueOnce({
    id: "config-zhipu-glm-5-3-flash",
    provider: "openai_compatible",
    display_name: "智谱 GLM-5.3-Flash",
    endpoint_host: "open.bigmodel.cn",
    model_id: "glm-5.3-flash",
    capability: "text",
    region: null,
    status: "community",
    experimental: false,
    credential_configured: true,
    credential_updated_at: "2026-09-03T00:00:00Z",
    configuration_version: "zhipu-glm-5-3-flash-v1",
    contract_version: "openai-compatible-chat-json-v1",
    last_validation_status: "not_run",
    last_validated_at: null,
    safe_error_code: "explicit_user_authorization_missing",
    native_web_search_status: "unsupported",
    native_web_search_checked_at: null,
    native_web_search_contract_version: null,
    native_web_search_safe_error_code: "NATIVE_WEB_SEARCH_NOT_ADAPTED",
  });
  renderInWorkspace(<ModelConfigForm role="admin" workspaceId="workspace-1" />);

  await screen.findByText("AI 模型连接");
  fireEvent.click(screen.getByRole("button", { name: "智谱 GLM-5.3-Flash" }));

  expect(screen.queryByLabelText("配置名称")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("服务地址")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("模型名称")).not.toBeInTheDocument();
  expect(screen.getByText(/只需填写智谱开放平台 API Key/)).toBeVisible();
  const key = screen.getByLabelText("模型服务密钥");
  fireEvent.change(key, { target: { value: "synthetic-zhipu-key" } });
  fireEvent.click(screen.getByRole("button", { name: "保存智谱模型配置" }));

  await waitFor(() => expect(saveModelConfig).toHaveBeenCalledWith(
    "workspace-1",
    "csrf-token",
    expect.objectContaining({
      provider: "openai_compatible",
      display_name: "智谱 GLM-5.3-Flash",
      base_url: "https://open.bigmodel.cn/api/paas/v4",
      model_id: "glm-5.3-flash",
      capabilities: ["text"],
      status: "community",
      api_key: "synthetic-zhipu-key",
    }),
  ));
  expect(key).toHaveValue("");
});
