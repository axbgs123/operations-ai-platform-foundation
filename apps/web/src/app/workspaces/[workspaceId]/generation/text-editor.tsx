"use client";

import { FormEvent, useEffect, useState } from "react";

import {
  cancelTextGeneration,
  editTextGeneration,
  readTextGeneration,
  requestTextGeneration,
  retryTextGeneration,
  TextGenerationRunData,
} from "@/lib/generation-api";
import { TaskStatus } from "@/components/generation/task-status";


const delay = (milliseconds: number) =>
  new Promise((resolve) => setTimeout(resolve, milliseconds));
const splitIds = (value: string) =>
  value.split(/[\s,，]+/).map((item) => item.trim()).filter(Boolean);

export type TextEditorDefaults = {
  accountId: string;
  modelConfigId: string;
  columnCampaignId: string;
  styleProfileId: string;
  inheritTitleStyle: boolean;
  inheritCopyStyle: boolean;
  inheritCoverStyle: boolean;
  viralReferenceIds: string[];
  factItemIds: string[];
  factSourceIds: string[];
  platform: "douyin" | "xiaohongshu";
  target: string;
};

export type TextGenerationDraft = {
  run: TextGenerationRunData | null;
  finalTitle: string;
  finalCopy: string;
};

export function TextEditor({
  workspaceId,
  defaults,
  deferFinalSave = false,
  onDraftChange,
}: {
  workspaceId: string;
  defaults?: TextEditorDefaults;
  deferFinalSave?: boolean;
  onDraftChange?: (draft: TextGenerationDraft) => void;
}) {
  const [accountId, setAccountId] = useState(defaults?.accountId ?? "");
  const [modelConfigId, setModelConfigId] = useState(defaults?.modelConfigId ?? "");
  const [columnCampaignId, setColumnCampaignId] = useState(
    defaults?.columnCampaignId ?? "",
  );
  const [styleProfileId, setStyleProfileId] = useState(
    defaults?.styleProfileId ?? "",
  );
  const [inheritTitleStyle, setInheritTitleStyle] = useState(
    defaults?.inheritTitleStyle ?? true,
  );
  const [inheritCopyStyle, setInheritCopyStyle] = useState(
    defaults?.inheritCopyStyle ?? true,
  );
  const [inheritCoverStyle, setInheritCoverStyle] = useState(
    defaults?.inheritCoverStyle ?? true,
  );
  const [viralIds, setViralIds] = useState(
    defaults?.viralReferenceIds.join(",") ?? "",
  );
  const [platform, setPlatform] = useState<"douyin" | "xiaohongshu">(
    defaults?.platform ?? "douyin",
  );
  const [target, setTarget] = useState(defaults?.target ?? "");
  const [prompt, setPrompt] = useState("");
  const [factIds, setFactIds] = useState(
    defaults?.factItemIds.join(",") ?? "",
  );
  const [sourceIds, setSourceIds] = useState(
    defaults?.factSourceIds.join(",") ?? "",
  );
  const [run, setRun] = useState<TextGenerationRunData | null>(null);
  const [finalTitle, setFinalTitle] = useState("");
  const [finalCopy, setFinalCopy] = useState("");
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const csrf = () => sessionStorage.getItem("workspace_csrf") ?? "";

  useEffect(() => {
    onDraftChange?.({ run, finalTitle, finalCopy });
  }, [finalCopy, finalTitle, onDraftChange, run]);

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
          column_campaign_id: columnCampaignId || null,
          risk_rule_version: "risk-v1",
          confirmed_fact_item_ids: splitIds(factIds),
          source_asset_ids: splitIds(sourceIds),
          style_profile_id:
            (inheritTitleStyle || inheritCopyStyle || inheritCoverStyle)
            && styleProfileId
              ? styleProfileId
              : null,
          viral_library_item_ids: splitIds(viralIds).slice(0, 3),
          user_prompt: prompt,
          style_switches: {
            title: inheritTitleStyle,
            copy: inheritCopyStyle,
            cover: inheritCoverStyle,
          },
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
          ? "复检完成，草稿已保存"
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
        <p className="text-sm font-medium text-[var(--brand)]">事实约束 · 可追溯引用</p>
        <h1 className="mt-2 text-3xl font-semibold">标题与文案生成</h1>
        <p className="mt-3 max-w-3xl text-[var(--text-secondary)]">
          提示词、风格和爆款引用只控制创意方向，不能覆盖已确认事实。
        </p>
      </header>
      <form className="grid gap-4 rounded-xl border border-[var(--border)] bg-white p-5 sm:grid-cols-2" onSubmit={generate}>
        <label className="space-y-2 text-sm">账号 ID<input aria-label="账号 ID" className="w-full rounded-lg border bg-white p-3" onChange={(event) => setAccountId(event.target.value)} required value={accountId} /></label>
        <label className="space-y-2 text-sm">模型配置 ID<input aria-label="模型配置 ID" className="w-full rounded-lg border bg-white p-3" onChange={(event) => setModelConfigId(event.target.value)} required value={modelConfigId} /></label>
        <label className="space-y-2 text-sm">栏目或活动 ID<input aria-label="栏目或活动 ID" className="w-full rounded-lg border bg-white p-3" onChange={(event) => setColumnCampaignId(event.target.value)} value={columnCampaignId} /></label>
        <label className="space-y-2 text-sm">风格档案 ID<input aria-label="风格档案 ID" className="w-full rounded-lg border bg-white p-3" onChange={(event) => setStyleProfileId(event.target.value)} value={styleProfileId} /></label>
        <fieldset className="grid gap-2 rounded-lg border border-[var(--border)] p-3 sm:col-span-2 sm:grid-cols-3">
          <legend className="px-2 text-sm">沿用已确认历史风格（默认开启）</legend>
          <label className="flex items-center gap-2 text-sm"><input checked={inheritTitleStyle} onChange={(event) => setInheritTitleStyle(event.target.checked)} type="checkbox" />标题风格</label>
          <label className="flex items-center gap-2 text-sm"><input checked={inheritCopyStyle} onChange={(event) => setInheritCopyStyle(event.target.checked)} type="checkbox" />文案风格</label>
          <label className="flex items-center gap-2 text-sm"><input checked={inheritCoverStyle} onChange={(event) => setInheritCoverStyle(event.target.checked)} type="checkbox" />封面风格</label>
        </fieldset>
        <label className="space-y-2 text-sm sm:col-span-2">爆款引用 ID（最多 3 条）<input aria-label="爆款引用 ID（最多 3 条）" className="w-full rounded-lg border bg-white p-3" onChange={(event) => setViralIds(event.target.value)} value={viralIds} /></label>
        <label className="space-y-2 text-sm">平台<select className="w-full rounded-lg border bg-white p-3" onChange={(event) => setPlatform(event.target.value as typeof platform)} value={platform}><option value="douyin">抖音</option><option value="xiaohongshu">小红书</option></select></label>
        <label className="space-y-2 text-sm">生成目标<input aria-label="生成目标" className="w-full rounded-lg border bg-white p-3" onChange={(event) => setTarget(event.target.value)} required value={target} /></label>
        <label className="space-y-2 text-sm sm:col-span-2">已确认事实 ID（逗号分隔）<input aria-label="已确认事实 ID（逗号分隔）" className="w-full rounded-lg border bg-white p-3" onChange={(event) => setFactIds(event.target.value)} value={factIds} /></label>
        <label className="space-y-2 text-sm sm:col-span-2">资料来源 ID（逗号分隔）<input aria-label="资料来源 ID（逗号分隔）" className="w-full rounded-lg border bg-white p-3" onChange={(event) => setSourceIds(event.target.value)} value={sourceIds} /></label>
        <label className="space-y-2 text-sm sm:col-span-2">补充提示词<textarea className="min-h-28 w-full rounded-lg border bg-white p-3" onChange={(event) => setPrompt(event.target.value)} value={prompt} /></label>
        <button className="rounded-xl bg-[var(--brand)] px-5 py-3 font-semibold text-white disabled:opacity-50 sm:col-span-2" disabled={busy === "generate"} type="submit">{busy === "generate" ? "生成中…" : "生成标题与文案"}</button>
      </form>

      {error ? <p className="rounded-xl border border-rose-300 bg-rose-50 p-4 text-rose-950">{error}</p> : null}
      {message ? <p className="rounded-xl border border-emerald-300 bg-emerald-50 p-4 text-emerald-950">{message}</p> : null}
      {run ? (
        <TaskStatus
          detail={run.status_detail}
          errorCode={run.error_code}
          onCancel={
            ["queued", "running"].includes(run.status) ? cancel : undefined
          }
          onRetry={
            ["failed", "cancelled"].includes(run.status) ? retry : undefined
          }
          progress={
            run.status === "queued"
              ? 10
              : run.status === "running"
                ? 50
                : 100
          }
          status={run.status}
        />
      ) : null}
      {run?.original_result ? (
        <section className="space-y-6">
          {run.original_result.warnings.map((warning) => <p className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-amber-950" key={warning}>{warning}</p>)}
          <article className="rounded-xl border border-[var(--border)] bg-white p-5">
            <h2 className="text-xl font-semibold">标题备选</h2>
            <div className="mt-4 grid gap-3">{run.original_result.titles.map((title) => <button className="rounded-xl border border-[var(--border)] p-3 text-left hover:border-[var(--brand)]" key={title} onClick={() => setFinalTitle(title)} type="button" aria-label={`采用${title}`}>{title}</button>)}</div>
          </article>
          <article className="grid gap-4 rounded-xl border border-[var(--border)] bg-white p-5">
            <label className="space-y-2">人工最终标题<input aria-label="人工最终标题" className="w-full rounded-lg border bg-white p-3" onChange={(event) => setFinalTitle(event.target.value)} value={finalTitle} /></label>
            <label className="space-y-2">人工最终文案<textarea aria-label="人工最终文案" className="min-h-64 w-full rounded-lg border bg-white p-3" onChange={(event) => setFinalCopy(event.target.value)} value={finalCopy} /></label>
            <div><h3 className="font-semibold">事实引用</h3><ul className="mt-2 text-sm text-[var(--text-secondary)]">{run.original_result.citations.map((citation) => <li key={citation.fact_item_id}>{citation.field_code}：{citation.value}</li>)}</ul></div>
            <p className="text-sm text-[var(--text-secondary)]">修改幅度 {(run.modification_magnitude * 100).toFixed(1)}%</p>
            {deferFinalSave ? (
              <p className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-950">
                标题和文案已保留在当前页面内存中；请进入“复核与保存”执行服务端事实与风控门禁。
              </p>
            ) : (
              <div className="flex flex-wrap gap-3"><button className="rounded-lg bg-[var(--brand)] px-4 py-2 font-medium text-white" disabled={busy === "save"} onClick={() => save("adopted")} type="button">复检并保存草稿</button><button className="rounded-lg border border-[var(--border)] px-4 py-2" disabled={busy === "save"} onClick={() => save("discarded")} type="button">放弃本稿</button></div>
            )}
          </article>
        </section>
      ) : null}
    </div>
  );
}
