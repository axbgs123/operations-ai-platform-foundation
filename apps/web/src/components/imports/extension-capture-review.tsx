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

export function ExtensionCaptureReview({ taskId }: { taskId: string }) {
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
  return (
    <section className="space-y-4 rounded-3xl border border-slate-800 bg-slate-900 p-6">
      <h2 className="text-2xl font-semibold">扩展识别结果待确认</h2>
      <p className="text-sm text-slate-400">
        扩展仅上传暂存截图；识别结果仍需在 Web 中确认后才写入正式快照。
      </p>
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
      <button
        className="rounded-xl bg-violet-400 px-5 py-3 font-semibold text-slate-950"
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
