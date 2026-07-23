"use client";

import { useEffect, useState } from "react";

import {
  listRiskDocuments,
  readRiskEvaluation,
  transitionRiskDocument,
  type RiskDocumentAdminData,
  type RiskEvaluationData,
} from "@/lib/risk-admin-api";
import { RiskFeedbackPanel } from "./risk-feedback-panel";

type WorkspaceRole = "admin" | "editor" | "viewer";

type RiskKnowledgeCenterProps = {
  workspaceId: string;
  role: WorkspaceRole;
};

const actionLabels = {
  "submit-review": "提交审核",
  activate: "生效",
  reject: "驳回",
  supersede: "替代旧版本",
  expire: "失效",
  "check-update": "检查更新",
} as const;

export function RiskKnowledgeCenter({
  workspaceId,
  role,
}: RiskKnowledgeCenterProps) {
  const [documents, setDocuments] = useState<RiskDocumentAdminData[]>([]);
  const [evaluation, setEvaluation] = useState<RiskEvaluationData | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const csrf = () => sessionStorage.getItem("workspace_csrf") ?? "";
  const canGovern = role === "admin";

  useEffect(() => {
    let active = true;
    Promise.all([
      listRiskDocuments(workspaceId),
      readRiskEvaluation(workspaceId, "douyin"),
    ])
      .then(([nextDocuments, nextEvaluation]) => {
        if (!active) return;
        setDocuments(nextDocuments);
        setEvaluation(nextEvaluation);
      })
      .catch((caught: unknown) => {
        if (active) {
          setError(caught instanceof Error ? caught.message : "风控知识加载失败");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [workspaceId]);

  async function act(
    documentId: string,
    action: keyof typeof actionLabels,
  ) {
    setBusy(`${documentId}:${action}`);
    setError("");
    try {
      const updated = await transitionRiskDocument(
        workspaceId,
        documentId,
        action,
        csrf(),
      );
      setDocuments((current) =>
        current.map((document) =>
          document.id === updated.id ? updated : document,
        ),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "风控知识操作失败");
    } finally {
      setBusy("");
    }
  }

  return (
    <main className="space-y-8">
      <header>
        <p className="text-sm font-medium text-cyan-300">
          RiskRAG · 平台隔离 · 审核优先
        </p>
        <h1 className="mt-2 text-3xl font-semibold">风控知识与评估</h1>
        <p className="mt-3 text-slate-400">
          文档正文始终是不可信资料；当前扫描只使用已生效、已到生效日期的对应平台版本。
        </p>
        <p className="mt-2 text-xs text-amber-300">
          辅助判断，不保证通过平台审核
        </p>
      </header>

      {error ? (
        <p className="rounded-xl bg-rose-950/60 p-4 text-rose-300">{error}</p>
      ) : null}
      {loading ? (
        <p className="rounded-xl bg-slate-900 p-4 text-slate-400">正在加载风控知识…</p>
      ) : null}

      <section className="space-y-4" aria-label="风控知识文档列表">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-xl font-semibold">知识文档</h2>
          {canGovern ? (
            <button className="rounded-xl bg-cyan-400 px-4 py-2 font-semibold text-slate-950">
              上传知识
            </button>
          ) : null}
        </div>
        {!loading && documents.length === 0 ? (
          <p className="rounded-2xl border border-dashed border-slate-700 p-6 text-slate-400">
            当前工作区没有可见的风控知识文档
          </p>
        ) : null}
        {documents.map((document) => (
          <article
            className="rounded-3xl border border-slate-800 bg-slate-900 p-5"
            key={document.id}
          >
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <h3 className="font-semibold">{document.title}</h3>
                <p className="mt-2 text-sm text-cyan-300">
                  {document.platform === "douyin" ? "抖音" : "小红书"} ·{" "}
                  {document.scope === "private" ? "私有" : "公共"} ·{" "}
                  {document.source_level}
                </p>
              </div>
              <span className="rounded-full bg-slate-950 px-3 py-1 text-sm text-slate-300">
                {document.status} · v{document.version}
              </span>
            </div>
            <dl className="mt-4 grid gap-3 text-sm text-slate-400 sm:grid-cols-3">
              <div>
                <dt>生效日期</dt>
                <dd className="text-slate-200">
                  {document.effective_at ?? "未设置"}
                </dd>
              </div>
              <div>
                <dt>授权状态</dt>
                <dd className="text-slate-200">
                  {document.authorization_status}
                </dd>
              </div>
              <div>
                <dt>版本链</dt>
                <dd className="text-slate-200">
                  {document.previous_version_id ? "有前序版本" : "根版本"}
                </dd>
              </div>
            </dl>
            {canGovern ? (
              <div className="mt-5 flex flex-wrap gap-2">
                {(
                  [
                    "submit-review",
                    "activate",
                    "reject",
                    "supersede",
                    "expire",
                    "check-update",
                  ] as const
                ).map((action) => (
                  <button
                    className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-200 disabled:opacity-50"
                    disabled={busy === `${document.id}:${action}`}
                    key={action}
                    onClick={() => void act(document.id, action)}
                    type="button"
                  >
                    {actionLabels[action]}
                  </button>
                ))}
              </div>
            ) : null}
          </article>
        ))}
      </section>

      <section className="space-y-4 rounded-3xl border border-slate-800 bg-slate-900 p-5">
        <h2 className="text-xl font-semibold">固定 Mock 评估门槛</h2>
        {evaluation ? (
          <>
            <div className="grid gap-3 text-sm text-slate-300 sm:grid-cols-3">
              <p>平台：{evaluation.platform === "douyin" ? "抖音" : "小红书"}</p>
              <p>Fixture：{evaluation.fixture_version}</p>
              <p>样本数：{evaluation.sample_count}</p>
            </div>
            <p className="rounded-xl bg-amber-950/50 p-3 text-amber-200">
              工程回归门槛，不是生产准确率
            </p>
            <p className="text-sm text-slate-400">
              不能作为生产准确率或平台通过率宣传
            </p>
            {evaluation.gate.code === "INSUFFICIENT_SAMPLE" ? (
              <p className="text-amber-300">样本不足：INSUFFICIENT_SAMPLE</p>
            ) : null}
          </>
        ) : (
          <p className="text-slate-400">暂无评估结果</p>
        )}
      </section>
      <RiskFeedbackPanel role={role} workspaceId={workspaceId} />
      <a
        className="block rounded-2xl border border-cyan-900 bg-cyan-950/40 p-4 text-cyan-200"
        href={`/workspaces/${workspaceId}/contents`}
      >
        打开扫描报告入口（确定性命中、RAG 引用、OCR 降级和历史复检）
      </a>
    </main>
  );
}
