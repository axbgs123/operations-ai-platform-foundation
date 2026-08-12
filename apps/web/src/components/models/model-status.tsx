import { useExperiencePreferences } from "@/components/workbench/experience-preferences-context";
import type { CopyMode } from "@/components/workbench/experience-preferences";
import type { ModelConfig } from "@/lib/model-api";
import {
  displayText,
  modelCapabilityCopy,
  modelChoiceCopy,
} from "@/components/workbench/operator-display-copy";

const easyModelStates: Record<string, string> = {
  community: "社区适配状态",
  configuration_required: "还没有完成所需配置",
  experimental: "试用状态，真实效果和费用尚未完成验收",
  incompatible: "当前配置不可用",
  provider_outcome_unknown: "模型服务是否已经计费暂时无法确认，请勿直接重复提交",
  verified: "已完成验收",
};

const easyValidationStates: Record<string, string> = {
  failed: "连接未通过",
  not_run: "尚未测试连接",
  passed: "连接成功（未调用模型）",
  provider_outcome_unknown: "连接结果暂时无法确认",
};

const easySafeErrors: Record<string, string> = {
  configuration_required: "还没有完成所需配置",
  explicit_user_authorization_missing: "尚未执行连接测试",
  MODEL_AUTHENTICATION_FAILED: "模型服务密钥无效，或没有访问千问接口的权限",
  MODEL_INVALID_RESPONSE: "千问接口返回了无法识别的结果",
  MODEL_PROVIDER_UNAVAILABLE: "暂时无法连接千问官方接口，请稍后重试",
  MODEL_RATE_LIMITED: "千问接口当前调用过于频繁，请稍后重试",
  MODEL_TIMEOUT: "连接千问接口超时，请检查网络后重试",
  MODEL_ENDPOINT_UNSAFE: "服务地址不安全，请使用公开的 HTTPS 地址",
  MODEL_NOT_FOUND: "服务可以连接，但没有找到填写的模型名称",
  provider_outcome_unknown: "模型服务结果暂时无法确认，请勿直接重复提交",
};

export function modelStateLabel(value: string, mode: CopyMode): string {
  if (mode === "professional") return value;
  return easyModelStates[value] ?? "需要管理员检查当前配置状态";
}

export function modelValidationLabel(value: string, mode: CopyMode): string {
  if (mode === "professional") {
    return value === "passed"
      ? "connection_passed_model_not_invoked"
      : value;
  }
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
  pending = false,
}: {
  configs: ModelConfig[];
  onStatusChange?: (config: ModelConfig) => void;
  onValidate?: (config: ModelConfig) => void;
  pending?: boolean;
}) {
  const { copyMode } = useExperiencePreferences();
  if (configs.length === 0) {
    return (
      <p className="rounded-xl border border-[var(--border)] bg-slate-50 p-4 text-sm text-[var(--text-secondary)]">
        {copyMode === "simple"
          ? "尚未配置真实模型；当前只能使用不会产生真实调用费用的演示能力。"
          : "尚未配置真实模型；当前只能使用 Mock 能力。"}
      </p>
    );
  }
  return (
    <ul className="space-y-3">
      {configs.map((config) => (
        <li
          className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 text-[var(--text-primary)]"
          key={config.id}
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <strong>{config.display_name ?? displayText(modelChoiceCopy(config.capability, config.model_id), copyMode)}</strong>
            <span className="rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-900">
              {modelStateLabel(
                config.experimental ? "experimental" : config.status,
                copyMode,
              )}
            </span>
          </div>
          <dl className="mt-3 grid gap-2 text-sm text-[var(--text-secondary)] sm:grid-cols-2">
            <div>能力：{displayText(modelCapabilityCopy(config.capability), copyMode)}</div>
            <div>
              {config.provider === "openai_compatible"
                ? `服务地址：${config.endpoint_host ?? "仅管理员可见"}`
                : `地域：${config.region ?? "不适用"}`}
            </div>
            <div>
              凭据：{config.credential_configured ? "已加密配置" : "未配置"}
            </div>
            <div>
              {copyMode === "simple" ? "连接状态" : "Connection status"}：
              {modelValidationLabel(config.last_validation_status, copyMode)}
            </div>
          </dl>
          {config.safe_error_code ? (
            <p className="mt-3 text-xs text-[var(--text-secondary)]">
              {copyMode === "simple" ? "连接提示" : "状态码"}：
              {modelSafeErrorLabel(config.safe_error_code, copyMode)}
            </p>
          ) : null}
          {onValidate ? (
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text-primary)] hover:border-[var(--brand)]"
                disabled={pending}
                onClick={() => onValidate(config)}
                type="button"
              >
                测试连接（不调用模型）
              </button>
              {onStatusChange ? (
                <button
                  className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text-primary)] hover:border-[var(--brand)]"
                  disabled={pending}
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
