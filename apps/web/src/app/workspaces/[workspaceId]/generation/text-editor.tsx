"use client";

import { FormEvent, useState } from "react";

import {
  cancelTextGeneration,
  editTextGeneration,
  readTextGeneration,
  requestTextGeneration,
  retryTextGeneration,
  TextGenerationRunData,
} from "@/lib/generation-api";


const delay = (milliseconds: number) =>
  new Promise((resolve) => setTimeout(resolve, milliseconds));
const splitIds = (value: string) =>
  value.split(/[\s,，]+/).map((item) => item.trim()).filter(Boolean);

export function TextEditor({ workspaceId }: { workspaceId: string }) {
  const [accountId, setAccountId] = useState("");
  const [modelConfigId, setModelConfigId] = useState("");
  const [platform, setPlatform] = useState<"douyin" | "xiaohongshu">("douyin");
  const [target, setTarget] = useState("");
  const [prompt, setPrompt] = useState("");
  const [factIds, setFactIds] = useState("");
  const [sourceIds, setSourceIds] = useState("");
  const [run, setRun] = useState<TextGenerationRunData | null>(null);
  const [finalTitle, setFinalTitle] = useState("");
  const [finalCopy, setFinalCopy] = useState("");
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const csrf = () => sessionStorage.getItem("workspace_csrf") ?? "";

  async function poll(current: TextGenerationRunData) {
    for (
      let attempt = 0;
      attempt < 20 && ["queued", "running"].includes(current.status);
      attempt += 1
    ) {
      await delay(500);
      current = await readTextGeneration(workspaceId, current.id);
      setRun(current);
    }
    return current;
  }

  function loadEditor(current: TextGenerationRunData) {
    setFinalTitle(current.final_title ?? current.original_result?.titles[0] ?? "");
    setFinalCopy(current.final_copy ?? current.original_result?.copy ?? "");
    if (current.status === "failed") {
      setError(current.status_detail ?? "生成失败，请重试。");
    }
  }

  async function generate(event: FormEvent) {
    event.preventDefault();
    setBusy("generate");
    setError("");
    setMessage("");
    try {
      let current = await requestTextGeneration(
        workspaceId,
        {
          account_id: accountId,
          model_config_id: modelConfigId,
          platform,
          target,
          risk_rule_version: "risk-v1",
          confirmed_fact_item_ids: splitIds(factIds),
          source_asset_ids: splitIds(sourceIds),
          viral_library_item_ids: [],
          user_prompt: prompt,
          style_switches: { title: false, copy: false, cover: false },
        },
        csrf(),
      );
      setRun(current);
      current = await poll(current);
      loadEditor(current);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "文本生成失败");
    } finally {
      setBusy("");
    }
  }

  async function save(adoptionStatus: "adopted" | "discarded") {
    if (!run) return;
    setBusy("save");
    setError("");
    try {
      const updated = await editTextGeneration(
        workspaceId,
        run.id,
        {
          final_title: finalTitle,
          final_copy: finalCopy,
          adoption_status: adoptionStatus,
        },
        csrf(),
      );
      setRun(updated);
      setMessage(
        adoptionStatus === "adopted"
          ? "已保存人工最终稿"
          : "已保存放弃状态",
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "保存失败");
    } finally {
      setBusy("");
    }
  }

  async function cancel() {
    if (!run) return;
    const updated = await cancelTextGeneration(workspaceId, run.id, csrf());
    setRun(updated);
    setMessage("生成任务已取消");
  }

  async function retry() {
    if (!run) return;
    setBusy("retry");
    setError("");
    try {
      let current = await retryTextGeneration(workspaceId, run.id, csrf());
      setRun(current);
      current = await poll(current);
      loadEditor(current);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "重试失败");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="space-y-8">
      <header>
        <p className="text-sm font-medium text-cyan-300">事实约束 · 可追溯引用</p>
        <h1 className="mt-2 text-3xl font-semibold">标题与文案生成</h1>
        <p className="mt-3 max-w-3xl text-slate-400">
          提示词、风格和爆款引用只控制创意方向，不能覆盖已确认事实。
        </p>
      </header>
      <form className="grid gap-4 rounded-2xl border border-slate-800 bg-slate-900 p-6 sm:grid-cols-2" onSubmit={generate}>
        <label className="space-y-2 text-sm">账号 ID<input aria-label="账号 ID" className="w-full rounded-lg bg-slate-950 p-3" onChange={(event) => setAccountId(event.target.value)} required value={accountId} /></label>
        <label className="space-y-2 text-sm">模型配置 ID<input aria-label="模型配置 ID" className="w-full rounded-lg bg-slate-950 p-3" onChange={(event) => setModelConfigId(event.target.value)} required value={modelConfigId} /></label>
        <label className="space-y-2 text-sm">平台<select className="w-full rounded-lg bg-slate-950 p-3" onChange={(event) => setPlatform(event.target.value as typeof platform)} value={platform}><option value="douyin">抖音</option><option value="xiaohongshu">小红书</option></select></label>
        <label className="space-y-2 text-sm">生成目标<input aria-label="生成目标" className="w-full rounded-lg bg-slate-950 p-3" onChange={(event) => setTarget(event.target.value)} required value={target} /></label>
        <label className="space-y-2 text-sm sm:col-span-2">已确认事实 ID（逗号分隔）<input className="w-full rounded-lg bg-slate-950 p-3" onChange={(event) => setFactIds(event.target.value)} value={factIds} /></label>
        <label className="space-y-2 text-sm sm:col-span-2">资料来源 ID（逗号分隔）<input className="w-full rounded-lg bg-slate-950 p-3" onChange={(event) => setSourceIds(event.target.value)} value={sourceIds} /></label>
        <label className="space-y-2 text-sm sm:col-span-2">补充提示词<textarea className="min-h-28 w-full rounded-lg bg-slate-950 p-3" onChange={(event) => setPrompt(event.target.value)} value={prompt} /></label>
        <button className="rounded-xl bg-cyan-400 px-5 py-3 font-semibold text-slate-950 disabled:opacity-50 sm:col-span-2" disabled={busy === "generate"} type="submit">{busy === "generate" ? "生成中…" : "生成标题与文案"}</button>
      </form>

      {error ? <p className="rounded-xl bg-rose-950/60 p-4 text-rose-300">{error}</p> : null}
      {message ? <p className="rounded-xl bg-emerald-950/60 p-4 text-emerald-300">{message}</p> : null}
      {run?.original_result ? (
        <section className="space-y-6">
          {run.original_result.warnings.map((warning) => <p className="rounded-xl border border-amber-800 bg-amber-950/40 p-4 text-amber-200" key={warning}>{warning}</p>)}
          <article className="rounded-2xl border border-slate-800 bg-slate-900 p-6">
            <h2 className="text-xl font-semibold">标题备选</h2>
            <div className="mt-4 grid gap-3">{run.original_result.titles.map((title) => <button className="rounded-xl border border-slate-700 p-3 text-left hover:border-cyan-500" key={title} onClick={() => setFinalTitle(title)} type="button" aria-label={`采用${title}`}>{title}</button>)}</div>
          </article>
          <article className="grid gap-4 rounded-2xl border border-slate-800 bg-slate-900 p-6">
            <label className="space-y-2">人工最终标题<input className="w-full rounded-lg bg-slate-950 p-3" onChange={(event) => setFinalTitle(event.target.value)} value={finalTitle} /></label>
            <label className="space-y-2">人工最终文案<textarea className="min-h-64 w-full rounded-lg bg-slate-950 p-3" onChange={(event) => setFinalCopy(event.target.value)} value={finalCopy} /></label>
            <div><h3 className="font-semibold">事实引用</h3><ul className="mt-2 text-sm text-slate-300">{run.original_result.citations.map((citation) => <li key={citation.fact_item_id}>{citation.field_code}：{citation.value}</li>)}</ul></div>
            <p className="text-sm text-slate-400">修改幅度 {(run.modification_magnitude * 100).toFixed(1)}%</p>
            <div className="flex flex-wrap gap-3"><button className="rounded-lg bg-emerald-500 px-4 py-2 font-medium text-slate-950" disabled={busy === "save"} onClick={() => save("adopted")} type="button">采用并保存</button><button className="rounded-lg border border-slate-700 px-4 py-2" disabled={busy === "save"} onClick={() => save("discarded")} type="button">放弃本稿</button></div>
          </article>
        </section>
      ) : null}
      {run && ["queued", "running"].includes(run.status) ? <button className="rounded-lg border border-rose-700 px-4 py-2 text-rose-300" onClick={cancel} type="button">取消任务</button> : null}
      {run && ["failed", "cancelled"].includes(run.status) ? <button className="rounded-lg border border-cyan-700 px-4 py-2 text-cyan-300" disabled={busy === "retry"} onClick={retry} type="button">按原上下文重试</button> : null}
    </div>
  );
}
