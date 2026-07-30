"use client";

import { useEffect, useState } from "react";

import {
  confirmExtensionCaptureTask,
  type ExtensionCaptureTask,
  readExtensionCaptureTask,
} from "@/lib/extension-capture-api";

type Candidate = { key: string; value: string; confidence: number };

function candidates(task: ExtensionCaptureTask | null): Candidate[] {
  const value = task?.recognition?.metric_candidates;
  if (!Array.isArray(value)) return [];
  return value.filter(
    (item): item is Candidate =>
      typeof item === "object" &&
      item !== null &&
      typeof item.key === "string" &&
      typeof item.value === "string" &&
      typeof item.confidence === "number",
  );
}

function unmappedText(task: ExtensionCaptureTask | null): string[] {
  const value = task?.recognition?.unmapped_text;
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

export function ExtensionCaptureReview({
  accountId,
  expectedPlatform,
  taskId,
}: {
  accountId: string;
  expectedPlatform: "douyin" | "xiaohongshu";
  taskId: string;
}) {
  const [task, setTask] = useState<ExtensionCaptureTask | null>(null);
  const [corrections, setCorrections] = useState<Record<string, string>>({});
  const [error, setError] = useState("");

  useEffect(() => {
    void readExtensionCaptureTask(taskId).then(setTask).catch(() => {
      setError("无法读取扩展识别任务");
    });
  }, [taskId]);

  async function confirm() {
    try {
      setTask(
        await confirmExtensionCaptureTask(
          taskId,
          accountId,
          corrections,
          sessionStorage.getItem("workspace_csrf") ?? "",
        ),
      );
    } catch {
      setError("人工确认失败");
    }
  }

  if (error) return <p role="alert">{error}</p>;
  if (!task) return <p>加载识别结果…</p>;
  const scopeMismatch = task.platform !== expectedPlatform;
  return (
    <section className="space-y-4 rounded-3xl border border-slate-800 bg-slate-900 p-6">
      <h2 className="text-2xl font-semibold">扩展识别结果待确认</h2>
      <p className="text-sm text-slate-400">
        扩展仅上传暂存截图；识别结果仍需在 Web 中确认后才写入正式快照。
      </p>
      <dl className="grid gap-2 text-sm sm:grid-cols-3">
        <div>
          <dt className="text-slate-400">平台</dt>
          <dd>{task.platform === "douyin" ? "抖音" : "小红书"}</dd>
        </div>
        <div>
          <dt className="text-slate-400">页面版本</dt>
          <dd>{task.page_version}</dd>
        </div>
        <div>
          <dt className="text-slate-400">任务状态</dt>
          <dd>{task.status}</dd>
        </div>
      </dl>
      <p className="text-sm text-amber-200">
        {task.provider_mode === "mock"
          ? "Mock 模式：未调用外部付费模型。"
          : `截图由阿里云百炼处理（地域 ${task.region ?? "未配置"}），可能包含敏感信息并产生模型调用费用。`}
      </p>
      {scopeMismatch ? (
        <p className="rounded-xl bg-rose-950/60 p-4 text-rose-300" role="alert">
          任务平台与当前筛选不匹配，已停止确认。请返回正确平台后重试。
        </p>
      ) : null}
      {candidates(task).map((candidate) => (
        <label className="block" key={candidate.key}>
          修正 {candidate.key}
          <input
            aria-label={`修正 ${candidate.key}`}
            className="mt-2 w-full rounded-xl bg-slate-950 px-4 py-3"
            defaultValue={candidate.value}
            onChange={(event) =>
              setCorrections((current) => ({
                ...current,
                [candidate.key]: event.target.value,
              }))
            }
          />
          <span className="ml-2 text-xs text-slate-400">
            OCR置信度 {Math.round(candidate.confidence * 100)}%
          </span>
        </label>
      ))}
      {unmappedText(task).length ? (
        <div className="rounded-xl bg-slate-950 p-4 text-sm text-slate-300">
          <p>未映射 OCR 文字（仅供人工查看，不写入正式指标）：</p>
          <ul>{unmappedText(task).map((item) => <li key={item}>{item}</li>)}</ul>
        </div>
      ) : null}
      <button
        className="rounded-xl bg-violet-400 px-5 py-3 font-semibold text-slate-950"
        disabled={scopeMismatch}
        onClick={confirm}
        type="button"
      >
        人工确认并写入快照
      </button>
      {task.formal_snapshot_ids.length ? (
        <p>已写入 {task.formal_snapshot_ids.length} 条正式快照。</p>
      ) : null}
    </section>
  );
}
