import { useExperiencePreferences } from "@/components/workbench/experience-preferences-context";
import type { CopyMode } from "@/components/workbench/experience-preferences";
import type { ModelConfig } from "@/lib/model-api";

const easyModelStates: Record<string, string> = {
  community: "社区适配状态",
  configuration_required: "还没有完成所需配置",
  experimental: "试用状态，真实效果和费用尚未完成验收",
  incompatible: "当前配置不可用",
  provider_outcome_unknown: "模型服务是否已经计费暂时无法确认，请勿直接重复提交",
  verified: "已完成验收",
};

const easyValidationStates: Record<string, string> = {
  failed: "验收未通过",
  not_run: "尚未验收",
  passed: "验收通过",
  provider_outcome_unknown: "模型服务结果暂时无法确认",
};

const easySafeErrors: Record<string, string> = {
  configuration_required: "还没有完成所需配置",
  explicit_user_authorization_missing: "尚未确认进行真实调用",
  provider_outcome_unknown: "模型服务是否已经计费暂时无法确认，请勿直接重复提交",
};

export function modelStateLabel(value: string, mode: CopyMode): string {
  if (mode === "professional") return value;
  return easyModelStates[value] ?? "需要管理员检查当前配置状态";
}

export function modelValidationLabel(value: string, mode: CopyMode): string {
  if (mode === "professional") return value;
  return easyValidationStates[value] ?? "需要管理员检查验收状态";
}

export function modelSafeErrorLabel(value: string, mode: CopyMode): string {
  if (mode === "professional") return value;
  return easySafeErrors[value] ?? "请联系管理员查看验收失败原因";
}

export function ModelStatus({
  configs,
  onStatusChange,
  onValidate,
}: {
  configs: ModelConfig[];
  onStatusChange?: (config: ModelConfig) => void;
  onValidate?: (config: ModelConfig) => void;
}) {
  const { copyMode } = useExperiencePreferences();
  if (configs.length === 0) {
    return (
      <p className="rounded-xl border border-slate-800 bg-slate-950 p-4 text-sm text-slate-400">
        尚未配置真实模型；当前只能使用 Mock 能力。
      </p>
    );
  }
  return (
    <ul className="space-y-3">
      {configs.map((config) => (
        <li
          className="rounded-xl border border-slate-800 bg-slate-950 p-4"
          key={config.id}
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <strong>{config.model_id}</strong>
            <span className="rounded-full bg-amber-950 px-3 py-1 text-xs text-amber-200">
              {modelStateLabel(
                config.experimental ? "experimental" : config.status,
                copyMode,
              )}
            </span>
          </div>
          <dl className="mt-3 grid gap-2 text-sm text-slate-400 sm:grid-cols-2">
            <div>能力：{config.capability}</div>
            <div>地域：{config.region ?? "不适用"}</div>
            <div>
              凭据：{config.credential_configured ? "已加密配置" : "未配置"}
            </div>
            <div>
              验证：{modelValidationLabel(config.last_validation_status, copyMode)}
            </div>
          </dl>
          {config.safe_error_code ? (
            <p className="mt-3 text-xs text-slate-500">
              {copyMode === "simple" ? "验收提示" : "状态码"}：
              {modelSafeErrorLabel(config.safe_error_code, copyMode)}
            </p>
          ) : null}
          {onValidate ? (
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                className="rounded-lg border border-slate-700 px-3 py-2 text-sm"
                onClick={() => onValidate(config)}
                type="button"
              >
                运行受控合同验证
              </button>
              {onStatusChange ? (
                <button
                  className="rounded-lg border border-slate-700 px-3 py-2 text-sm"
                  onClick={() => onStatusChange(config)}
                  type="button"
                >
                  {config.status === "incompatible"
                    ? "重新启用配置"
                    : "禁用配置"}
                </button>
              ) : null}
            </div>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
