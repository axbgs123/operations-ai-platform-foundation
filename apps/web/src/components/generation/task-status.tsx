"use client";


export type GenerationTaskStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "retrying";

const statusPresentation: Record<
  GenerationTaskStatus,
  { label: string; color: string }
> = {
  queued: { label: "等待执行", color: "text-slate-300" },
  running: { label: "正在执行", color: "text-cyan-300" },
  succeeded: { label: "执行成功", color: "text-emerald-300" },
  failed: { label: "执行失败", color: "text-rose-300" },
  cancelled: { label: "已取消", color: "text-amber-300" },
  retrying: { label: "正在重试", color: "text-violet-300" },
};

type TaskStatusProps = {
  status: GenerationTaskStatus;
  progress?: number;
  detail?: string | null;
  errorCode?: string | null;
  onCancel?: () => void;
  onRetry?: () => void;
};

export function TaskStatus({
  status,
  progress,
  detail,
  errorCode,
  onCancel,
  onRetry,
}: TaskStatusProps) {
  const presentation = statusPresentation[status];
  const normalizedProgress =
    progress === undefined ? undefined : Math.min(100, Math.max(0, progress));
  const cancellable = ["queued", "running", "retrying"].includes(status);
  const retryable = ["failed", "cancelled"].includes(status);

  return (
    <section
      className="space-y-3 rounded-xl border border-slate-700 bg-slate-950/70 p-4"
      role="status"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className={`font-medium ${presentation.color}`}>
          {presentation.label}
        </p>
        {errorCode ? (
          <code className="rounded bg-rose-950 px-2 py-1 text-xs text-rose-200">
            {errorCode}
          </code>
        ) : null}
      </div>
      {normalizedProgress !== undefined ? (
        <div
          aria-label="任务进度"
          aria-valuemax={100}
          aria-valuemin={0}
          aria-valuenow={normalizedProgress}
          className="h-2 overflow-hidden rounded-full bg-slate-800"
          role="progressbar"
        >
          <div
            className="h-full bg-cyan-400 transition-[width]"
            style={{ width: `${normalizedProgress}%` }}
          />
        </div>
      ) : null}
      {detail ? <p className="text-sm text-slate-300">{detail}</p> : null}
      <div className="flex flex-wrap gap-3">
        {cancellable && onCancel ? (
          <button
            className="rounded-lg border border-rose-700 px-3 py-2 text-sm text-rose-300"
            onClick={onCancel}
            type="button"
          >
            取消任务
          </button>
        ) : null}
        {retryable && onRetry ? (
          <button
            className="rounded-lg border border-cyan-700 px-3 py-2 text-sm text-cyan-300"
            onClick={onRetry}
            type="button"
          >
            重试任务
          </button>
        ) : null}
      </div>
    </section>
  );
}
