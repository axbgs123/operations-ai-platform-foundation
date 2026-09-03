"use client";

import { FormEvent, useEffect, useState } from "react";

import { GuidedPageHeader } from "@/components/workbench/guided-page-header";
import { useExperiencePreferences } from "@/components/workbench/experience-preferences-context";
import {
  displayText,
  modelChoiceCopy,
} from "@/components/workbench/operator-display-copy";
import { readOperationsAccess } from "@/lib/operations-api";
import {
  getModelCatalog,
  createModelValidation,
  listModelConfigs,
  saveModelConfig,
  updateModelConfigStatus,
  verifyNativeWebSearch,
  type ModelCatalog,
  type ModelConfig,
} from "@/lib/model-api";
import {
  modelSafeErrorLabel,
  modelStateLabel,
  modelValidationLabel,
  ModelStatus,
} from "./model-status";


type WorkspaceRole = "admin" | "editor" | "viewer" | "demo";
type ProviderMode = "qianwen" | "zhipu_glm_5_3_flash" | "openai_compatible";

const ZHIPU_GLM_5_3_FLASH = {
  displayName: "智谱 GLM-5.3-Flash",
  baseUrl: "https://open.bigmodel.cn/api/paas/v4",
  modelId: "glm-5.3-flash",
} as const;

const formControlClasses = (
  "mt-2 w-full rounded-xl border border-[var(--border)] "
  + "bg-[var(--surface)] px-4 py-3 text-[var(--text-primary)] "
  + "placeholder:text-[var(--text-secondary)] "
  + "disabled:cursor-not-allowed disabled:bg-slate-100 "
  + "disabled:text-[var(--text-secondary)]"
);

export function ModelConfigForm({
  workspaceId,
  role: suppliedRole,
}: {
  workspaceId: string;
  role?: WorkspaceRole;
}) {
  const { copyMode } = useExperiencePreferences();
  const [role, setRole] = useState<WorkspaceRole | null>(
    suppliedRole ?? null,
  );
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null);
  const [configs, setConfigs] = useState<ModelConfig[]>([]);
  const [providerMode, setProviderMode] = useState<ProviderMode>("qianwen");
  const [modelId, setModelId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [compatibleModelId, setCompatibleModelId] = useState("");
  const region = "cn-beijing" as const;
  const [apiKey, setApiKey] = useState("");
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState(false);

  useEffect(() => {
    let active = true;
    Promise.all([
      getModelCatalog(workspaceId),
      listModelConfigs(workspaceId),
      suppliedRole
        ? Promise.resolve({ role: suppliedRole })
        : readOperationsAccess(workspaceId),
    ])
      .then(([nextCatalog, nextConfigs, access]) => {
        if (!active) return;
        setCatalog(nextCatalog);
        setConfigs(nextConfigs);
        setRole(access.role as WorkspaceRole);
        setModelId(nextCatalog.models[0]?.model_id ?? "");
      })
      .catch((caught) => {
        if (active) {
          setMessage(
            caught instanceof Error ? caught.message : "加载模型状态失败",
          );
        }
      });
    return () => {
      active = false;
    };
  }, [suppliedRole, workspaceId]);

  const selected = catalog?.models.find((item) => item.model_id === modelId);
  const canManage = role === "admin";
  const displayInternalState = (value: string) => {
    return modelStateLabel(value, copyMode);
  };

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canManage || (providerMode === "qianwen" && !selected)) return;
    setPending(true);
    setMessage("");
    try {
      const saved = await saveModelConfig(
        workspaceId,
        sessionStorage.getItem("workspace_csrf") ?? "",
        providerMode === "qianwen"
          ? {
              provider: "qianwen",
              model_id: selected!.model_id,
              region,
              provider_workspace_id: null,
              capabilities: [selected!.capability],
              status: "experimental",
              api_key: apiKey,
            }
          : providerMode === "zhipu_glm_5_3_flash"
          ? {
              provider: "openai_compatible",
              display_name: ZHIPU_GLM_5_3_FLASH.displayName,
              base_url: ZHIPU_GLM_5_3_FLASH.baseUrl,
              model_id: ZHIPU_GLM_5_3_FLASH.modelId,
              region: null,
              provider_workspace_id: null,
              capabilities: ["text"],
              status: "community",
              api_key: apiKey,
            }
          : {
              provider: "openai_compatible",
              display_name: displayName,
              base_url: baseUrl,
              model_id: compatibleModelId,
              region: null,
              provider_workspace_id: null,
              capabilities: ["text"],
              status: "community",
              api_key: apiKey,
            },
      );
      setConfigs((current) => [
        ...current.filter((item) => item.id !== saved.id),
        saved,
      ]);
      setApiKey("");
      setMessage("配置已安全保存；密钥输入已清空，现在可以测试连接");
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "保存失败");
    } finally {
      setPending(false);
    }
  }

  async function validate(config: ModelConfig) {
    setPending(true);
    try {
      const result = await createModelValidation(
        workspaceId,
        sessionStorage.getItem("workspace_csrf") ?? "",
        {
          model_config_id: config.id,
          region:
            config.provider === "openai_compatible"
              ? "provider-managed"
              : config.region ?? "cn-beijing",
          capability: config.capability,
          model_id: config.model_id,
          max_calls: 1,
          max_input_tokens: 100,
          max_output_tokens: 100,
          max_images: config.capability === "image" ? 1 : 0,
          max_cost_microunits: 1000,
          confirm_real_call: true,
        },
      );
      setMessage(
        result.result === "passed"
          ? copyMode === "simple"
            ? config.provider === "openai_compatible"
              ? "连接成功：密钥、服务地址和模型名称均可用；尚未发送生成内容。"
              : "连接成功：模型服务密钥与千问官方接口可以正常通信；尚未调用具体模型。"
            : "Connection succeeded: credentials and endpoint are reachable; no generation request was sent."
          : result.result === "not_run"
          ? `未运行：${result.safe_error_code
            ? modelSafeErrorLabel(result.safe_error_code, copyMode)
            : copyMode === "simple" ? "尚未获得真实调用授权" : "未授权"}`
          : `连接失败：${result.safe_error_code
            ? modelSafeErrorLabel(result.safe_error_code, copyMode)
            : modelValidationLabel(result.result, copyMode)}`,
      );
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "验证发起失败");
    } finally {
      setPending(false);
    }
  }

  async function changeStatus(config: ModelConfig) {
    setPending(true);
    setMessage("");
    const nextStatus =
      config.status === "incompatible"
        ? config.provider === "openai_compatible"
          ? "community"
          : "experimental"
        : "incompatible";
    try {
      const saved = await updateModelConfigStatus(
        workspaceId,
        config.id,
        nextStatus,
        sessionStorage.getItem("workspace_csrf") ?? "",
      );
      setConfigs((current) =>
        current.map((item) => (item.id === saved.id ? saved : item)),
      );
      setMessage(
        nextStatus === "incompatible"
          ? copyMode === "simple"
            ? "配置已禁用；新任务不会调用该模型服务"
            : "配置已禁用；新任务不会调用该 Provider"
          : "配置已重新启用；调用前仍会检查预算和配置版本",
      );
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "状态更新失败");
    } finally {
      setPending(false);
    }
  }

  async function validateNativeSearch(config: ModelConfig) {
    const confirmed = window.confirm(
      "这会真实调用一次模型自带的联网搜索，费用由你的模型供应商收取。是否继续？",
    );
    if (!confirmed) return;
    setPending(true);
    setMessage("");
    try {
      const result = await verifyNativeWebSearch(
        workspaceId,
        config.id,
        sessionStorage.getItem("workspace_csrf") ?? "",
      );
      setConfigs((current) =>
        current.map((item) =>
          item.id === config.id
            ? {
                ...item,
                native_web_search_status: result.status,
                native_web_search_checked_at: result.checked_at,
                native_web_search_contract_version: result.contract_version,
                native_web_search_safe_error_code: result.safe_error_code,
              }
            : item,
        ),
      );
      if (result.status === "supported") {
        setMessage(
          `模型联网可用：已收到 ${result.source_count} 个可验证来源。`,
        );
      } else if (result.status === "unsupported") {
        setMessage("当前模型接入方式还没有适配原生联网搜索。");
      } else {
        setMessage(
          `模型联网检测失败：${result.safe_error_code
            ? modelSafeErrorLabel(result.safe_error_code, copyMode)
            : "请检查模型权限和网络后重试"}`,
        );
      }
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "联网检测发起失败");
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-6 text-[var(--text-primary)] sm:p-8">
      <GuidedPageHeader
        context={{
          simple: "可以使用千问官方服务，也可以接入支持 OpenAI 格式的文本模型。连接测试不会发送生成内容。",
          professional: "支持千问 AI 平台官方固定接口与工作区自带 OpenAI-compatible Chat Completions 文本模型；连接测试只请求模型列表，不发送 Prompt。真实调用可能产生费用。",
        }}
        pageId="settingsModels"
        secondaryActions={(
          <span className="rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-900">
            {displayInternalState("experimental")}
          </span>
        )}
      />

      <div className="mt-6">
        <ModelStatus
          configs={configs}
          onNativeSearchValidate={canManage ? validateNativeSearch : undefined}
          pending={pending}
          onStatusChange={canManage ? changeStatus : undefined}
          onValidate={canManage ? validate : undefined}
        />
      </div>

      {!canManage ? (
        <p className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
          {role === "demo"
            ? "演示工作区只使用 Mock，不允许保存真实配置。"
            : "只读状态：只有管理员可以管理模型连接。"}
        </p>
      ) : (
        <form className="mt-6 grid gap-4 sm:grid-cols-2" onSubmit={submit}>
          <div
            aria-label="模型接入方式"
            className="grid grid-cols-1 gap-2 sm:col-span-2 sm:grid-cols-3"
            role="group"
          >
            <button
              aria-pressed={providerMode === "qianwen"}
              className={providerMode === "qianwen" ? "rounded-xl bg-[var(--brand)] px-4 py-3 font-semibold text-white" : "rounded-xl border border-[var(--border)] px-4 py-3 font-semibold"}
              onClick={() => setProviderMode("qianwen")}
              type="button"
            >
              千问官方
            </button>
            <button
              aria-pressed={providerMode === "zhipu_glm_5_3_flash"}
              className={providerMode === "zhipu_glm_5_3_flash" ? "rounded-xl bg-[var(--brand)] px-4 py-3 font-semibold text-white" : "rounded-xl border border-[var(--border)] px-4 py-3 font-semibold"}
              onClick={() => setProviderMode("zhipu_glm_5_3_flash")}
              type="button"
            >
              智谱 GLM-5.3-Flash
            </button>
            <button
              aria-pressed={providerMode === "openai_compatible"}
              className={providerMode === "openai_compatible" ? "rounded-xl bg-[var(--brand)] px-4 py-3 font-semibold text-white" : "rounded-xl border border-[var(--border)] px-4 py-3 font-semibold"}
              onClick={() => setProviderMode("openai_compatible")}
              type="button"
            >
              OpenAI 兼容
            </button>
          </div>
          {providerMode === "qianwen" ? (
            <>
              <label className="text-sm sm:col-span-2">
                {copyMode === "simple" ? "模型能力" : "精确模型"}
                <select
                  aria-label={copyMode === "simple" ? "模型能力" : "精确模型"}
                  className={formControlClasses}
                  onChange={(event) => setModelId(event.target.value)}
                  value={modelId}
                >
                  {(catalog?.models ?? []).map((model) => (
                    <option key={model.model_id} value={model.model_id}>
                      {displayText(modelChoiceCopy(model.capability, model.model_id), copyMode)}
                    </option>
                  ))}
                </select>
              </label>
            </>
          ) : providerMode === "openai_compatible" ? (
            <>
              <label className="text-sm">
                配置名称
                <input aria-label="配置名称" className={formControlClasses} maxLength={80} onChange={(event) => setDisplayName(event.target.value)} required value={displayName} />
              </label>
              <label className="text-sm">
                模型名称
                <input aria-label="模型名称" className={formControlClasses} maxLength={160} onChange={(event) => setCompatibleModelId(event.target.value)} required value={compatibleModelId} />
              </label>
              <label className="text-sm sm:col-span-2">
                服务地址
                <input aria-label="服务地址" className={formControlClasses} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://你的模型服务地址/v1" required type="url" value={baseUrl} />
                <span className="mt-2 block text-[var(--text-secondary)]">只支持 OpenAI 格式的文本接口；正式环境必须使用 HTTPS。</span>
              </label>
            </>
          ) : (
            <div className="rounded-xl border border-violet-200 bg-violet-50 p-4 text-sm leading-6 text-[var(--text-primary)] sm:col-span-2">
              <strong className="block">智谱 GLM-5.3-Flash</strong>
              <span className="mt-1 block text-[var(--text-secondary)]">
                国内官方服务地址和模型名称已经配置好，只需填写智谱开放平台 API Key。当前按文字模型接入，可用于生成、分析和运营智能体对话。
              </span>
            </div>
          )}
          <p className="rounded-xl border border-[var(--border)] bg-slate-50 p-4 text-sm text-[var(--text-secondary)] sm:col-span-2">
            {providerMode === "openai_compatible"
              ? "费用由模型供应商结算，平台只限制调用次数和文字量。"
              : providerMode === "zhipu_glm_5_3_flash"
              ? "GLM-5.3-Flash 为新发布模型；连接成功只代表密钥和模型可用，实际费用与额度以智谱开放平台为准。图片和模型原生联网暂未在本平台开放。"
              : copyMode === "simple"
              ? "使用千问 AI 平台官方固定接口，不需要填写业务空间 ID。"
              : "Uses the fixed Qianwen AI Platform endpoint; no Provider Workspace ID or custom Base URL is accepted."}
          </p>
          <label className="text-sm sm:col-span-2">
            {copyMode === "simple" ? "模型服务密钥" : "API Key"}
            <input
              aria-label={copyMode === "simple" ? "模型服务密钥" : "API Key"}
              autoComplete="new-password"
              className={formControlClasses}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder="留空保留现有密钥；输入新值即替换"
              type="password"
              value={apiKey}
            />
            <span className="mt-2 block text-[var(--text-secondary)]">
              {copyMode === "simple"
                ? "密钥保存后不会再次显示；更换密钥需要重新输入。"
                : "API Key 保存后不回显；留空保留现有密钥，输入新值即替换。"}
            </span>
          </label>
          <button
            className="rounded-xl bg-[var(--brand)] px-5 py-3 font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50 sm:col-span-2"
            disabled={pending || (providerMode === "qianwen" && !selected)}
            type="submit"
          >
            {pending
              ? "正在保存…"
              : providerMode === "zhipu_glm_5_3_flash"
                ? "保存智谱模型配置"
              : providerMode === "openai_compatible"
                ? "保存兼容模型配置"
                : "保存或替换密钥"}
          </button>
        </form>
      )}
      {message ? (
        <p className="mt-4 text-sm text-[var(--info)]" role="status">
          {message}
        </p>
      ) : null}
    </section>
  );
}
