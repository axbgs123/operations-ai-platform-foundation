import type { ModelConfig } from "@/lib/model-api";


export function ModelStatus({
  configs,
  onStatusChange,
  onValidate,
}: {
  configs: ModelConfig[];
  onStatusChange?: (config: ModelConfig) => void;
  onValidate?: (config: ModelConfig) => void;
}) {
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
              {config.experimental ? "experimental" : config.status}
            </span>
          </div>
          <dl className="mt-3 grid gap-2 text-sm text-slate-400 sm:grid-cols-2">
            <div>能力：{config.capability}</div>
            <div>地域：{config.region ?? "不适用"}</div>
            <div>
              凭据：{config.credential_configured ? "已加密配置" : "未配置"}
            </div>
            <div>验证：{config.last_validation_status}</div>
          </dl>
          {config.safe_error_code ? (
            <p className="mt-3 text-xs text-slate-500">
              状态码：{config.safe_error_code}
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
