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


const { saveModelConfig, updateModelConfigStatus } = vi.hoisted(() => ({
  saveModelConfig: vi.fn(),
  updateModelConfigStatus: vi.fn(),
}));
const { saveModelUsagePolicy, createModelValidation } = vi.hoisted(() => ({
  saveModelUsagePolicy: vi.fn(),
  createModelValidation: vi.fn(),
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
  listModelConfigs: vi.fn(async () => []),
  listModelUsagePolicies: vi.fn(async () => []),
  saveModelConfig,
  updateModelConfigStatus,
  saveModelUsagePolicy,
  createModelValidation,
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
  });
  saveModelUsagePolicy.mockReset();
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
  saveModelUsagePolicy.mockResolvedValue({ version: 1 });
  createModelValidation.mockReset();
  createModelValidation.mockResolvedValue({
    result: "not_run",
    safe_error_code: "explicit_user_authorization_missing",
  });
  sessionStorage.setItem("workspace_csrf", "csrf-token");
});

afterEach(cleanup);

test("admin sees only catalog choices and clears the key after save", async () => {
  localStorage.setItem("operations-ai:copy-mode:member-admin", "professional");
  renderInWorkspace(<ModelConfigForm role="admin" workspaceId="workspace-1" />);

  expect(await screen.findByText("模型配置")).toBeInTheDocument();
  expect(screen.getByLabelText("Provider")).toHaveValue("qianwen");
  expect(screen.getByLabelText("精确模型")).toHaveValue(
    "qwen3.5-plus-2026-04-20",
  );
  expect(screen.queryByLabelText(/base_url/i)).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Provider Workspace ID")).not.toBeInTheDocument();
  expect(screen.getByText("experimental")).toBeInTheDocument();
  expect(screen.getByText(/数据将发送到所选地域/)).toBeInTheDocument();
  expect(screen.getByText(/调用可能产生费用/)).toBeInTheDocument();
  expect(screen.getByText("工作区用量政策（UTC 日界线）")).toBeInTheDocument();

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
      api_key: "synthetic-one-time-key",
    }),
  );
  expect(key).toHaveValue("");
  expect(
    screen.getByRole("button", { name: "运行受控合同验证" }),
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

  fireEvent.click(screen.getByRole("button", { name: "保存用量政策" }));
  await waitFor(() => expect(saveModelUsagePolicy).toHaveBeenCalledOnce());
});

test("viewer receives safe status without credential controls", async () => {
  renderInWorkspace(
    <ModelConfigForm role="viewer" workspaceId="workspace-1" />,
    "viewer",
  );

  expect(await screen.findByText("模型配置")).toBeInTheDocument();
  expect(screen.getByText(
    "配置要使用的千问能力和每日费用上限；真实调用前请先确认地域和预算。",
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
    "配置要使用的千问能力和每日费用上限；真实调用前请先确认地域和预算。",
  )).toBeVisible();
  expect(screen.getByText(
    "密钥保存后不会再次显示；更换密钥需要重新输入。",
  )).toBeVisible();
  expect(screen.getByText(
    "真实调用可能产生费用；没有设置每日上限时，系统不会允许调用。",
  )).toBeVisible();
  expect(screen.getByText(
    "试用状态，真实效果和费用尚未完成验收",
  )).toBeVisible();
  expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
});
