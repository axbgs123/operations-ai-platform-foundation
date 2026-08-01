"use client";

import { FormEvent, useEffect, useState } from "react";

import { GuidedPageHeader } from "@/components/workbench/guided-page-header";
import { useExperiencePreferences } from "@/components/workbench/experience-preferences-context";
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
import { ModelStatus } from "./model-status";


type WorkspaceRole = "admin" | "editor" | "viewer" | "demo";

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
  const [region, setRegion] = useState<"cn-beijing" | "ap-southeast-1">(
    "cn-beijing",
  );
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
    if (copyMode === "professional") return value;
    return {
      configuration_required: "还没有完成所需配置",
      experimental: "试用状态，真实效果和费用尚未完成验收",
      provider_outcome_unknown: "模型服务是否已经计费暂时无法确认，请勿直接重复提交",
    }[value] ?? value;
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
      setMessage("配置已安全保存；密钥输入已清空");
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
        result.result === "not_run"
          ? `未运行：${displayInternalState(result.safe_error_code ?? "未授权")}`
          : `验证状态：${displayInternalState(result.result)}`,
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
          ? "配置已禁用；新任务不会调用该 Provider"
          : "配置已重新启用；调用前仍会检查预算和配置版本",
      );
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "状态更新失败");
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="rounded-xl border bg-white p-6 sm:p-8">
      <GuidedPageHeader
        context={{
          simple: "真实调用可能产生费用；没有设置每日上限时，系统不会允许调用。",
          professional: "数据将发送到所选地域的阿里云百炼服务；调用可能产生费用。Embedding 当前固定内部合同为 qianwen-text-embedding-v4-d1024-v1，上游尚无已确认日期快照。",
        }}
        pageId="settingsModels"
        secondaryActions={(
          <span className="rounded-full bg-amber-950 px-3 py-1 text-xs text-amber-200">
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
        <p className="mt-5 rounded-xl bg-slate-950 p-4 text-sm text-slate-300">
          {role === "demo"
            ? "演示工作区只使用 Mock，不允许保存真实配置。"
            : "只读状态：只有管理员可以管理凭据和预算。"}
        </p>
      ) : (
        <form className="mt-6 grid gap-4 sm:grid-cols-2" onSubmit={submit}>
          <label className="text-sm">
            {copyMode === "simple" ? "模型服务" : "Provider"}
            <input
              aria-label="Provider"
              className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3"
              disabled
              value="qianwen"
            />
          </label>
          <label className="text-sm">
            精确模型
            <select
              aria-label="精确模型"
              className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3"
              onChange={(event) => setModelId(event.target.value)}
              value={modelId}
            >
              {(catalog?.models ?? []).map((model) => (
                <option key={model.model_id} value={model.model_id}>
                  {model.model_id} · {model.capability}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            地域
            <select
              aria-label="地域"
              className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3"
              onChange={(event) =>
                setRegion(
                  event.target.value as
                    | "cn-beijing"
                    | "ap-southeast-1",
                )
              }
              value={region}
            >
              {(catalog?.regions ?? []).map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm sm:col-span-2">
            API Key
            <input
              aria-label="API Key"
              autoComplete="new-password"
              className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3"
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
            className="rounded-xl bg-cyan-400 px-5 py-3 font-semibold text-slate-950 disabled:opacity-50 sm:col-span-2"
            disabled={pending || !selected}
            type="submit"
          >
            {pending ? "正在保存…" : "保存或替换密钥"}
          </button>
        </form>
      )}
      {canManage ? (
        <form
          className="mt-8 rounded-2xl border border-slate-800 bg-slate-950 p-5"
          onSubmit={savePolicy}
        >
          <h2 className="text-lg font-semibold">
            工作区用量政策（UTC 日界线）
          </h2>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <label className="text-sm">
              能力
              <select
                className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 p-2"
                onChange={(event) =>
                  setPolicyCapability(
                    event.target.value as typeof policyCapability,
                  )
                }
                value={policyCapability}
              >
                <option value="text">text</option>
                <option value="vision">vision</option>
                <option value="embedding">embedding</option>
                <option value="image">image</option>
              </select>
            </label>
            {[
              ["max_concurrent_calls", "最大并发", 2],
              ["max_calls_per_minute", "每分钟调用", 20],
              ["daily_request_limit", "每日调用", 100],
              ["daily_input_token_limit", "每日输入 token", 100000],
              ["daily_output_token_limit", "每日输出 token", 20000],
              [
                "daily_embedding_token_limit",
                "每日 Embedding token",
                100000,
              ],
              ["daily_ocr_image_limit", "每日 OCR 图片", 100],
              ["daily_generated_image_limit", "每日生成图片", 10],
              [
                "daily_cost_limit_microunits",
                "每日费用上限（CNY microunits）",
                1000000,
              ],
            ].map(([name, label, value]) => (
              <label className="text-sm" key={String(name)}>
                {label}
                <input
                  className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 p-2"
                  defaultValue={value}
                  min="0"
                  name={String(name)}
                  type="number"
                />
              </label>
            ))}
          </div>
          <button
            className="mt-4 rounded-xl border border-cyan-600 px-4 py-2 text-cyan-200"
            disabled={pending}
            type="submit"
          >
            保存用量政策
          </button>
        </form>
      ) : null}
      {message ? (
        <p className="mt-4 text-sm text-cyan-300" role="status">
          {message}
        </p>
      ) : null}
    </section>
  );
}
