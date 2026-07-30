"use client";

import { useEffect, useState } from "react";

import {
  listRiskFeedbackCandidates,
  reviewRiskFeedback,
  type RiskRuleCandidateData,
} from "@/lib/risk-admin-api";

type RiskFeedbackPanelProps = {
  workspaceId: string;
  role: "admin" | "editor" | "viewer";
  platform: "douyin" | "xiaohongshu";
};

export function RiskFeedbackPanel({
  workspaceId,
  role,
  platform,
}: RiskFeedbackPanelProps) {
  const [candidates, setCandidates] = useState<RiskRuleCandidateData[]>([]);
  const [error, setError] = useState("");
  const csrf = () => sessionStorage.getItem("workspace_csrf") ?? "";

  useEffect(() => {
    let active = true;
    listRiskFeedbackCandidates(workspaceId, platform)
      .then((next) => {
        if (active) setCandidates(next);
      })
      .catch((caught: unknown) => {
        if (active) {
          setError(caught instanceof Error ? caught.message : "反馈加载失败");
        }
      });
    return () => {
      active = false;
    };
  }, [platform, workspaceId]);

  async function review(feedbackId: string, status: "approved" | "rejected") {
    try {
      await reviewRiskFeedback(workspaceId, feedbackId, csrf(), status);
      setCandidates((current) =>
        current.filter((candidate) => candidate.feedback_id !== feedbackId),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "反馈审核失败");
    }
  }

  return (
    <section className="space-y-4 rounded-xl border border-[var(--border)] bg-white p-5">
      <div>
        <h2 className="text-xl font-semibold">待审核反馈候选</h2>
        <p className="mt-2 text-sm text-[var(--text-secondary)]">
          审核通过也只形成私有人工规则更新候选，不会自动修改公共规则。
        </p>
      </div>
      {error ? <p className="text-red-700" role="alert">{error}</p> : null}
      {role === "editor" ? (
        <p className="text-sm text-[var(--text-secondary)]">
          编辑者可提交反馈，不能审核或发布规则
        </p>
      ) : null}
      {candidates.length === 0 ? (
        <p className="text-[var(--text-secondary)]">暂无待审核候选</p>
      ) : (
        candidates.map((candidate) => (
          <article
            className="rounded-xl border border-[var(--border)] bg-[var(--surface-subtle)] p-4"
            key={candidate.feedback_id}
          >
            <p className="font-medium">
              {candidate.feedback_type} · {candidate.finding_reference}
            </p>
            <p className="mt-2 text-sm text-[var(--text-secondary)]">
              {candidate.scope === "workspace_private"
                ? "仅工作区私有候选"
                : "公共候选（禁止自动发布）"}
            </p>
            {role === "admin" ? (
              <div className="mt-3 flex gap-2">
                <button
                  className="rounded-lg bg-emerald-400 px-3 py-2 text-sm font-semibold text-slate-950"
                  onClick={() => void review(candidate.feedback_id, "approved")}
                  type="button"
                >
                  审核候选
                </button>
                <button
                  className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm"
                  onClick={() => void review(candidate.feedback_id, "rejected")}
                  type="button"
                >
                  驳回候选
                </button>
              </div>
            ) : null}
          </article>
        ))
      )}
    </section>
  );
}
