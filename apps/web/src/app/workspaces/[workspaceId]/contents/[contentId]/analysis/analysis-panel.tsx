"use client";

import { useState } from "react";

import {
  AnalysisRunData,
  AnalysisSuggestionData,
  createAnalysisFeedback,
  markAnalysisViewed,
  readAnalysisRun,
  requestContentAnalysis,
  saveAnalysisSuggestion,
  updateAnalysisSuggestion,
} from "@/lib/analysis-api";
import {
  AnalysisFeedback,
  AnalysisRating,
} from "@/components/feedback/analysis-feedback";


const sectionLabels = {
  title_issues: "标题问题",
  copy_issues: "文案问题",
  cover_issues: "封面问题",
  causal_hypotheses: "原因假设（非因果结论）",
} as const;

const delay = (milliseconds: number) => new Promise((resolve) => setTimeout(resolve, milliseconds));

export function AnalysisPanel({ contentId }: { workspaceId: string; contentId: string }) {
  const [run, setRun] = useState<AnalysisRunData | null>(null);
  const [suggestions, setSuggestions] = useState<Record<string, AnalysisSuggestionData>>({});
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const csrf = () => sessionStorage.getItem("workspace_csrf") ?? "";

  async function start() {
    setBusy("analysis");
    setError("");
    setMessage("");
    try {
      let current = await requestContentAnalysis(contentId, csrf());
      setRun(current);
      for (let attempt = 0; attempt < 20 && ["pending", "running"].includes(current.status); attempt += 1) {
        await delay(500);
        current = await readAnalysisRun(contentId, current.id);
        setRun(current);
      }
      if (current.status === "failed") setError("分析输出未通过证据校验，请重新触发。");
      if (["pending", "running"].includes(current.status)) setMessage("分析仍在后台运行，可稍后刷新查看。");
      if (current.status === "succeeded") {
        try {
          await markAnalysisViewed(contentId, current.id, csrf());
        } catch {
          setError("分析已展示，但查看记录暂未同步，请稍后重试。");
        }
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "分析启动失败");
    } finally {
      setBusy("");
    }
  }

  async function feedback(rating: AnalysisRating) {
    if (!run) return;
    const idempotencyKey = globalThis.crypto.randomUUID();
    await createAnalysisFeedback(
      contentId,
      run.id,
      rating,
      csrf(),
      idempotencyKey,
    );
  }

  async function save(recommendationId: string) {
    if (!run) return;
    setBusy(recommendationId);
    try {
      const saved = await saveAnalysisSuggestion(contentId, run.id, recommendationId, csrf());
      setSuggestions((current) => ({ ...current, [recommendationId]: saved }));
      setMessage("建议已保存");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "建议保存失败");
    } finally {
      setBusy("");
    }
  }

  async function adopt(recommendationId: string) {
    const suggestion = suggestions[recommendationId];
    if (!suggestion) return;
    setBusy(recommendationId);
    try {
      const adopted = await updateAnalysisSuggestion(contentId, suggestion.id, "adopted", csrf());
      setSuggestions((current) => ({ ...current, [recommendationId]: adopted }));
      setMessage("已标记为采用");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "采用状态更新失败");
    } finally {
      setBusy("");
    }
  }

  const report = run?.status === "succeeded" ? run.report : null;
  return (
    <section className="space-y-8">
      <header>
        <p className="text-sm font-medium text-cyan-300">确定性证据包 · 可追溯版本</p>
        <h1 className="mt-2 text-3xl font-semibold">内容深度分析</h1>
        <p className="mt-3 max-w-3xl text-slate-400">结论只引用当前内容、已确认快照和账号动态基准；原因项均为待验证假设。</p>
      </header>
      <button className="rounded-xl bg-cyan-400 px-5 py-3 font-semibold text-slate-950 disabled:opacity-50" disabled={busy === "analysis"} onClick={start} type="button">
        {busy === "analysis" ? "分析中…" : "开始深度分析"}
      </button>
      {error ? <p className="rounded-xl bg-rose-950/60 p-4 text-rose-300">{error}</p> : null}
      {message ? <p className="rounded-xl bg-emerald-950/60 p-4 text-emerald-300">{message}</p> : null}
      {run ? <p className="text-sm text-slate-400">模型 {run.model_version} · Prompt {run.prompt_version} · 算法 {run.algorithm_version} · 基准 {run.benchmark_algorithm_version}</p> : null}

      {report ? (
        <div className="space-y-6">
          {report.degradation_notice ? <p className="rounded-xl border border-amber-800 bg-amber-950/40 p-4 text-amber-200">{report.degradation_notice}</p> : null}
          <article className="rounded-2xl border border-slate-800 bg-slate-900 p-6">
            <h2 className="text-xl font-semibold">数据表现</h2>
            <p className="mt-3 text-slate-300">{report.data_performance.summary}</p>
            {report.data_performance.trend_conclusion ? <p className="mt-2 text-slate-400">{report.data_performance.trend_conclusion}</p> : null}
          </article>
          {Object.entries(sectionLabels).map(([key, label]) => (
            <article className="rounded-2xl border border-slate-800 bg-slate-900 p-6" key={key}>
              <h2 className="text-xl font-semibold">{label}</h2>
              <ul className="mt-3 space-y-3 text-slate-300">
                {report[key as keyof typeof sectionLabels].map((item) => <li key={item.summary}>{item.summary} <span className="text-xs text-slate-500">置信度 {item.confidence}</span></li>)}
              </ul>
            </article>
          ))}
          <article className="rounded-2xl border border-slate-800 bg-slate-900 p-6">
            <h2 className="text-xl font-semibold">证据引用</h2>
            <ul className="mt-3 space-y-3 text-slate-300">
              {report.evidence.map((citation) => (
                <li key={citation.evidence_id}>
                  <code className="text-cyan-300">{citation.evidence_id}</code>
                  <span className="ml-2 text-slate-400">{citation.interpretation}</span>
                </li>
              ))}
            </ul>
          </article>
          <article className="rounded-2xl border border-slate-800 bg-slate-900 p-6">
            <h2 className="text-xl font-semibold">建议与下一次实验</h2>
            <div className="mt-4 space-y-4">
              {report.recommendations.map((recommendation) => {
                const saved = suggestions[recommendation.id];
                return <div className="rounded-xl bg-slate-950 p-4" key={recommendation.id}>
                  <p>{recommendation.summary}</p><p className="mt-2 text-slate-400">{recommendation.action}</p>
                  {!saved ? <button className="mt-3 rounded-lg border border-cyan-700 px-3 py-2 text-cyan-300" disabled={busy === recommendation.id} onClick={() => save(recommendation.id)} type="button">保存建议</button> : saved.adoption_status === "adopted" ? <p className="mt-3 text-emerald-300">已采用</p> : <button className="mt-3 rounded-lg border border-emerald-700 px-3 py-2 text-emerald-300" disabled={busy === recommendation.id} onClick={() => adopt(recommendation.id)} type="button">标记为已采用</button>}
                </div>;
              })}
            </div>
            <ul className="mt-5 space-y-2 text-slate-300">{report.next_experiments.map((experiment) => <li key={experiment.summary}>{experiment.summary}：{experiment.change}（成功指标：{experiment.success_metric}）</li>)}</ul>
          </article>
          <AnalysisFeedback onSubmit={feedback} />
        </div>
      ) : null}
    </section>
  );
}
