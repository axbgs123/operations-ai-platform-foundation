"use client";

import { DragEvent, useState } from "react";

import { saveAccountConfiguration } from "@/lib/account-api";


export function AccountConfigEditor({
  accountId,
  workspaceId,
  initialObjectives,
  initialWeights,
  initialBenchmarkSampleSize = 30,
}: {
  accountId: string;
  workspaceId: string;
  initialObjectives: string[];
  initialWeights: Record<string, number>;
  initialBenchmarkSampleSize?: number;
}) {
  const [objectives, setObjectives] = useState(initialObjectives);
  const [weights, setWeights] = useState(initialWeights);
  const [sampleSize, setSampleSize] = useState(initialBenchmarkSampleSize);
  const [draggedIndex, setDraggedIndex] = useState<number>();
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState(false);

  function dropObjective(event: DragEvent<HTMLLIElement>, targetIndex: number) {
    event.preventDefault();
    if (draggedIndex === undefined || draggedIndex === targetIndex) return;
    const reordered = [...objectives];
    const [dragged] = reordered.splice(draggedIndex, 1);
    reordered.splice(targetIndex, 0, dragged);
    setObjectives(reordered);
    setDraggedIndex(undefined);
  }

  async function save() {
    const total = Object.values(weights).reduce((sum, value) => sum + value, 0);
    if (total <= 0) {
      setMessage("至少需要一个大于 0 的指标权重");
      return;
    }
    const normalized = Object.fromEntries(
      Object.entries(weights).map(([key, value]) => [key, value / total]),
    );
    setPending(true);
    setMessage("");
    try {
      const csrf = sessionStorage.getItem("workspace_csrf") ?? "";
      await saveAccountConfiguration(workspaceId, accountId, csrf, {
        objectives,
        metric_weights: normalized,
        benchmark_sample_size: sampleSize,
      });
      setWeights(normalized);
      setMessage("已保存为新版本");
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "保存失败");
    } finally {
      setPending(false);
    }
  }

  function restoreDefaults() {
    setObjectives(initialObjectives);
    setWeights(initialWeights);
    setSampleSize(initialBenchmarkSampleSize);
    setMessage("已恢复账号默认值，保存后生效");
  }

  return (
    <section className="rounded-3xl border border-slate-800 bg-slate-900 p-6">
      <h1 className="text-2xl font-semibold">账号目标与指标权重</h1>
      <p className="mt-2 text-sm text-slate-400">拖拽调整目标优先级</p>
      <ol className="mt-5 space-y-2">
        {objectives.map((objective, index) => (
          <li
            className="cursor-grab rounded-xl border border-slate-700 bg-slate-950 px-4 py-3"
            draggable
            key={objective}
            onDragOver={(event) => event.preventDefault()}
            onDragStart={() => setDraggedIndex(index)}
            onDrop={(event) => dropObjective(event, index)}
          >
            <span className="mr-3 text-slate-500">{index + 1}</span>
            {objective}
          </li>
        ))}
      </ol>

      <div className="mt-7 grid gap-4 sm:grid-cols-2">
        {Object.entries(weights).map(([metric, value]) => (
          <label className="text-sm" key={metric}>
            {metric} 权重
            <input
              aria-label={`${metric} 权重`}
              className="mt-2 w-full px-4 py-3"
              min="0"
              onChange={(event) => setWeights({ ...weights, [metric]: Number(event.target.value) })}
              step="0.01"
              type="number"
              value={value}
            />
          </label>
        ))}
      </div>
      <label className="mt-5 block text-sm">
        动态基准参考最近作品数
        <input
          className="mt-2 w-full px-4 py-3"
          max="500"
          min="1"
          onChange={(event) => setSampleSize(Number(event.target.value))}
          type="number"
          value={sampleSize}
        />
      </label>

      <div className="mt-6 flex flex-wrap gap-3">
        <button
          className="rounded-xl bg-cyan-400 px-5 py-3 font-semibold text-slate-950 disabled:opacity-50"
          disabled={pending}
          onClick={save}
          type="button"
        >
          {pending ? "正在保存…" : "保存并创建新版本"}
        </button>
        <button
          className="rounded-xl border border-slate-700 px-5 py-3"
          onClick={restoreDefaults}
          type="button"
        >
          一键恢复账号默认
        </button>
      </div>
      {message ? <p className="mt-4 text-sm text-cyan-300">{message}</p> : null}
    </section>
  );
}
