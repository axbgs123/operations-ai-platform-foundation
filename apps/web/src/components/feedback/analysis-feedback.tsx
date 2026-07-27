"use client";

import { useState } from "react";


export type AnalysisRating = "useful" | "not_useful";

export function AnalysisFeedback({
  onSubmit,
}: {
  onSubmit: (rating: AnalysisRating) => Promise<void>;
}) {
  const [selected, setSelected] = useState<AnalysisRating | null>(null);
  const [submitting, setSubmitting] = useState<AnalysisRating | null>(null);
  const [message, setMessage] = useState("");
  const [failed, setFailed] = useState(false);

  async function submit(rating: AnalysisRating) {
    setSubmitting(rating);
    setMessage("");
    setFailed(false);
    try {
      await onSubmit(rating);
      setSelected(rating);
      setMessage("反馈已记录");
    } catch {
      setFailed(true);
    } finally {
      setSubmitting(null);
    }
  }

  return (
    <section aria-label="分析反馈" className="space-y-2">
      <div className="flex gap-3">
        {([
          ["useful", "有用"],
          ["not_useful", "无用"],
        ] as const).map(([rating, label]) => (
          <button
            aria-pressed={selected === rating}
            className="rounded-lg border border-slate-700 px-4 py-2 text-slate-300 disabled:opacity-50 aria-pressed:border-emerald-600 aria-pressed:text-emerald-300"
            disabled={submitting !== null}
            key={rating}
            onClick={() => void submit(rating)}
            type="button"
          >
            {submitting === rating ? "提交中…" : label}
          </button>
        ))}
      </div>
      {message ? (
        <p className="text-sm text-emerald-300" role="status">{message}</p>
      ) : null}
      {failed ? (
        <p className="text-sm text-rose-300" role="alert">反馈提交失败，请重试</p>
      ) : null}
    </section>
  );
}
