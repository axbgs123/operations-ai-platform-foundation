"use client";

import { FormEvent, useEffect, useState } from "react";

import { GuidedPageHeader } from "@/components/workbench/guided-page-header";
import { useExperiencePreferences } from "@/components/workbench/experience-preferences-context";
import {
  displayText,
  modelCapabilityCopy,
  modelChoiceCopy,
} from "@/components/workbench/operator-display-copy";
import { readOperationsAccess } from "@/lib/operations-api";
import {
  getModelCatalog,
  createModelValidation,
  listModelConfigs,
  saveModelConfig,
  saveModelUsagePolicy,
  updateModelConfigStatus,
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

const formControlClasses = (
  "mt-2 w-full rounded-xl border border-[var(--border)] "
  + "bg-[var(--surface)] px-4 py-3 text-[var(--text-primary)] "
  + "placeholder:text-[var(--text-secondary)] "
  + "disabled:cursor-not-allowed disabled:bg-slate-100 "
  + "disabled:text-[var(--text-secondary)]"
);

const policyControlClasses = (
  "mt-1 w-full rounded-lg border border-[var(--border)] "
  + "bg-[var(--surface)] p-2 text-[var(--text-primary)] "
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
  const [modelId, setModelId] = useState("");
  const region = "cn-beijing" as const;
  const [apiKey, setApiKey] = useState("");
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState(false);
  const [policyCapability, setPolicyCapability] = useState<
    "text" | "vision" | "embedding" | "image"
  >("text");

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
    if (!selected || !canManage) return;
    setPending(true);
    setMessage("");
    try {
      const saved = await saveModelConfig(
        workspaceId,
        sessionStorage.getItem("workspace_csrf") ?? "",
        {
          provider: "qianwen",
          model_id: selected.model_id,
          region,
          provider_workspace_id: null,
          capabilities: [selected.capability],
          status: "experimental",
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

  async function savePolicy(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setPending(true);
    try {
      await saveModelUsagePolicy(
        workspaceId,
        sessionStorage.getItem("workspace_csrf") ?? "",
        {
          capability: policyCapability,
          enabled: true,
          max_concurrent_calls: Number(form.get("max_concurrent_calls")),
          max_calls_per_minute: Number(form.get("max_calls_per_minute")),
          daily_request_limit: Number(form.get("daily_request_limit")),
          daily_input_token_limit: Number(
            form.get("daily_input_token_limit"),
          ),
          daily_output_token_limit: Number(
            form.get("daily_output_token_limit"),
          ),
          daily_embedding_token_limit: Number(
            form.get("daily_embedding_token_limit"),
          ),
          daily_ocr_image_limit: Number(
            form.get("daily_ocr_image_limit"),
          ),
          daily_generated_image_limit: Number(
            form.get("daily_generated_image_limit"),
          ),
          daily_cost_limit_microunits: Number(
            form.get("daily_cost_limit_microunits"),
          ),
          currency: "CNY",
        },
      );
      setMessage("用量政策已保存；每日边界为 UTC 00:00");
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "政策保存失败");
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
          region: config.region ?? "cn-beijing",
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
            ? "连接成功：模型服务密钥与千问官方接口可以正常通信；尚未调用具体模型。"
            : "Connection succeeded: the API Key can authenticate with the Qianwen endpoint; no model was invoked."
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
      config.status === "incompatible" ? "experimental" : "incompatible";
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

  return (
    <section className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-6 text-[var(--text-primary)] sm:p-8">
      <GuidedPageHeader
        context={{
          simple: "真实调用可能产生费用；没有设置每日上限时，系统不会允许调用。",
          professional: "配置使用千问 AI 平台官方固定接口；连接测试只验证 API Key，不调用模型。真实模型调用可能产生费用。Embedding 当前固定内部合同为 qianwen-text-embedding-v4-d1024-v1，上游尚无已确认日期快照。",
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
          onStatusChange={canManage ? changeStatus : undefined}
          onValidate={canManage ? validate : undefined}
        />
      </div>

      {!canManage ? (
        <p className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
          {role === "demo"
            ? "演示工作区只使用 Mock，不允许保存真实配置。"
            : "只读状态：只有管理员可以管理凭据和预算。"}
        </p>
      ) : (
        <form className="mt-6 grid gap-4 sm:grid-cols-2" onSubmit={submit}>
          <label className="text-sm">
            {copyMode === "simple" ? "模型服务" : "Provider"}
            <input
              aria-label={copyMode === "simple" ? "模型服务" : "Provider"}
              className={formControlClasses}
              disabled
              value="qianwen"
            />
          </label>
          <label className="text-sm">
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
          <p className="rounded-xl border border-[var(--border)] bg-slate-50 p-4 text-sm text-[var(--text-secondary)] sm:col-span-2">
            {copyMode === "simple"
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
            disabled={pending || !selected}
            type="submit"
          >
            {pending ? "正在保存…" : "保存或替换密钥"}
          </button>
        </form>
      )}
      {canManage ? (
        <form
          className="mt-8 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5 text-[var(--text-primary)]"
          onSubmit={savePolicy}
        >
          <h2 className="text-lg font-semibold">
            工作区用量政策（UTC 日界线）
          </h2>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <label className="text-sm">
              能力
              <select
                className={policyControlClasses}
                onChange={(event) =>
                  setPolicyCapability(
                    event.target.value as typeof policyCapability,
                  )
                }
                value={policyCapability}
              >
                {(["text", "vision", "embedding", "image"] as const).map((capability) => (
                  <option key={capability} value={capability}>
                    {displayText(modelCapabilityCopy(capability), copyMode)}
                  </option>
                ))}
              </select>
            </label>
            {[
              ["max_concurrent_calls", "最大并发", 2],
              ["max_calls_per_minute", "每分钟调用", 20],
              ["daily_request_limit", "每日调用", 100],
              ["daily_input_token_limit", copyMode === "simple" ? "每日输入文字量" : "每日输入 token", 100000],
              ["daily_output_token_limit", copyMode === "simple" ? "每日输出文字量" : "每日输出 token", 20000],
              [
                "daily_embedding_token_limit",
                copyMode === "simple" ? "每日资料检索文字量" : "每日 Embedding token",
                100000,
              ],
              ["daily_ocr_image_limit", copyMode === "simple" ? "每日图片文字识别数量" : "每日 OCR 图片", 100],
              ["daily_generated_image_limit", "每日生成图片", 10],
              [
                "daily_cost_limit_microunits",
                copyMode === "simple" ? "每日费用上限（人民币最小计费单位）" : "每日费用上限（CNY microunits）",
                1000000,
              ],
            ].map(([name, label, value]) => (
              <label className="text-sm" key={String(name)}>
                {label}
                <input
                  className={policyControlClasses}
                  defaultValue={value}
                  min="0"
                  name={String(name)}
                  type="number"
                />
              </label>
            ))}
          </div>
          <button
            className="mt-4 rounded-xl bg-[var(--brand)] px-4 py-2 font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
            disabled={pending}
            type="submit"
          >
            保存用量政策
          </button>
        </form>
      ) : null}
      {message ? (
        <p className="mt-4 text-sm text-[var(--info)]" role="status">
          {message}
        </p>
      ) : null}
    </section>
  );
}
