"use client";

import { useEffect, useState } from "react";

import {
  listRiskDocuments,
  readRiskEvaluation,
  transitionRiskDocument,
  type RiskDocumentAdminData,
  type RiskEvaluationData,
} from "@/lib/risk-admin-api";
import { useOptionalExperiencePreferences } from "@/components/workbench/experience-preferences-context";
import { GuidedPageHeader } from "@/components/workbench/guided-page-header";
import {
  displayCopy,
  displayText,
  knowledgeTermCopy,
  riskDocumentStatusCopy,
} from "@/components/workbench/operator-display-copy";
import { useWorkbenchShellContext } from "@/components/workbench/workspace-shell";
import { DesktopOnlyNotice, Panel, StatusBadge } from "@/components/workbench/ui";
import { RiskFeedbackPanel } from "./risk-feedback-panel";

type WorkspaceRole = "admin" | "editor" | "viewer";
type RiskPlatform = "douyin" | "xiaohongshu";

type RiskKnowledgeCenterProps = {
  workspaceId: string;
  role?: WorkspaceRole;
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
  role: suppliedRole,
}: RiskKnowledgeCenterProps) {
  const context = useWorkbenchShellContext();
  const copyMode =
    useOptionalExperiencePreferences()?.copyMode ?? "simple";
  const role = suppliedRole ?? context?.role ?? "viewer";
  const [platform, setPlatform] = useState<RiskPlatform>("douyin");
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
      listRiskDocuments(workspaceId, platform),
      readRiskEvaluation(workspaceId, platform),
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
  }, [platform, workspaceId]);

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
    <div className="space-y-8">
      <GuidedPageHeader pageId="riskKnowledge" />
      <Panel title="文档生命周期">
        <p className="text-sm font-semibold">
          草稿 → 已解析 → 待审核 → 生效 → 已替代/已失效
        </p>
        <p className="mt-2 text-sm text-[var(--text-secondary)]">
          网页更新只产生待审核版本，旧版本保留历史追溯，不覆盖既有扫描。
        </p>
      </Panel>

      {error ? (
        <p className="rounded-xl border border-red-200 bg-red-50 p-4 text-red-800" role="alert">{error}</p>
      ) : null}
      {loading ? (
        <p className="rounded-xl border bg-white p-4 text-[var(--text-secondary)]" role="status">正在加载风控知识…</p>
      ) : null}

      <section className="space-y-4" aria-label="风控知识文档列表">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-end gap-4">
            <h2 className="text-xl font-semibold">知识文档</h2>
            <label className="grid gap-1 text-sm font-medium">
              风控平台
              <select
                aria-label="风控平台"
                className="min-h-10 rounded-lg border border-[var(--border)] bg-white px-3"
                onChange={(event) => {
                  setLoading(true);
                  setError("");
                  setDocuments([]);
                  setEvaluation(null);
                  setPlatform(event.target.value as RiskPlatform);
                }}
                value={platform}
              >
                <option value="douyin">抖音</option>
                <option value="xiaohongshu">小红书</option>
              </select>
            </label>
          </div>
          {canGovern ? (
            <button className="rounded-xl bg-cyan-400 px-4 py-2 font-semibold text-slate-950">
              上传知识
            </button>
          ) : null}
        </div>
        {!loading && documents.length === 0 ? (
          <p className="rounded-2xl border border-dashed p-6 text-[var(--text-secondary)]">
            当前工作区没有可见的风控知识文档
          </p>
        ) : null}
        {documents.map((document) => (
          <article
            className="rounded-xl border border-[var(--border)] bg-white p-5"
            key={document.id}
          >
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <h3 className="font-semibold">{document.title}</h3>
                <p className="mt-2 text-sm text-blue-700">
                  {document.platform === "douyin" ? "抖音" : "小红书"} ·{" "}
                  {document.scope === "private" ? "私有" : "公共"} ·{" "}
                  {document.source_level}
                </p>
              </div>
              <StatusBadge tone={document.status === "active" ? "success" : "neutral"}>
                {displayText(
                  riskDocumentStatusCopy(document.status, document.version),
                  copyMode,
                )}
              </StatusBadge>
            </div>
            <dl className="mt-4 grid gap-3 text-sm text-[var(--text-secondary)] sm:grid-cols-3">
              <div>
                <dt>来源</dt>
                <dd className="text-[var(--text-primary)]">
                  {document.source_url ?? document.private_document_id ?? "当前记录未提供"}
                </dd>
              </div>
              <div>
                <dt>发布日期</dt>
                <dd className="text-[var(--text-primary)]">
                  {document.published_at ?? "未设置"}
                </dd>
              </div>
              <div>
                <dt>生效日期</dt>
                <dd className="text-[var(--text-primary)]">
                  {document.effective_at ?? "未设置"}
                </dd>
              </div>
              <div>
                <dt>授权状态</dt>
                <dd className="text-[var(--text-primary)]">
                  {document.authorization_status}
                </dd>
              </div>
              <div>
                <dt>版本链</dt>
                <dd className="text-[var(--text-primary)]">
                  {document.previous_version_id ? "有前序版本" : "根版本"}
                </dd>
              </div>
              <div>
                <dt>最近检查</dt>
                <dd className="text-[var(--text-primary)]">
                  {document.accessed_at ?? "尚未检查"}
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
                    className="rounded-lg border px-3 py-2 text-sm font-medium disabled:opacity-50"
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

      <Panel
        description={displayText(displayCopy(
          "只展示规则片段标识、位置和引用完整性；完整私有正文不进入列表 DOM。",
          "只展示 Chunk 标识、位置和引用完整性；完整私有正文不进入列表 DOM。",
        ), copyMode)}
        title={displayText(displayCopy(
          `${displayText(knowledgeTermCopy("chunk"), copyMode)}与${
            displayText(knowledgeTermCopy("citation"), copyMode)
          }`,
          "Chunks 与引用检查",
        ), copyMode)}
      >
        <p className="text-sm text-[var(--text-secondary)]">
          {displayText(displayCopy(
            "引用检查必须引用本次判断资料中同平台、同工作区的有效规则片段。",
            "Citation 必须引用本次 Evidence Bundle 中同平台、同工作区的有效 Chunk。",
          ), copyMode)}
        </p>
        <p className="mt-2 text-sm font-semibold text-amber-800">
          S5 只能作为低置信度提示，不能独立支撑高风险结论
        </p>
        <div className="mt-4 md:hidden">
          <DesktopOnlyNotice action="复杂知识库审核" />
        </div>
      </Panel>

      <section className="space-y-4 rounded-xl border border-[var(--border)] bg-white p-5">
        <h2 className="text-xl font-semibold">
          {displayText(displayCopy(
            `${knowledgeTermCopy("mock").simple}门槛`,
            `固定 ${knowledgeTermCopy("mock").professional} 评估门槛`,
          ), copyMode)}
        </h2>
        {evaluation ? (
          <>
            <div className="grid gap-3 text-sm text-[var(--text-secondary)] sm:grid-cols-3">
              <p>平台：{evaluation.platform === "douyin" ? "抖音" : "小红书"}</p>
              <p>{copyMode === "simple" ? "评估版本" : "Fixture"}：{evaluation.fixture_version}</p>
              <p>样本数：{evaluation.sample_count}</p>
            </div>
            <p className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-amber-900">
              工程回归门槛，不是生产准确率
            </p>
            <p className="text-sm text-[var(--text-secondary)]">
              不能作为生产准确率或平台通过率宣传
            </p>
            {evaluation.gate.code === "INSUFFICIENT_SAMPLE" ? (
              <p className="text-amber-900">
                {displayText(displayCopy(
                  "样本不足",
                  "样本不足：INSUFFICIENT_SAMPLE",
                ), copyMode)}
              </p>
            ) : null}
          </>
        ) : (
          <p className="text-[var(--text-secondary)]">暂无评估结果</p>
        )}
      </section>
      <p className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm font-semibold text-amber-950">
        辅助判断，不保证通过平台审核
      </p>
      <RiskFeedbackPanel
        platform={platform}
        role={role}
        workspaceId={workspaceId}
      />
      <a
        className="block rounded-xl border border-blue-200 bg-blue-50 p-4 text-blue-800"
        href={`/workspaces/${workspaceId}/contents`}
      >
        {displayText(displayCopy(
          `打开扫描报告入口（确定性命中、${
            knowledgeTermCopy("rag").simple
          }引用、${knowledgeTermCopy("ocr").simple}降级和历史复检）`,
          `打开扫描报告入口（确定性命中、${
            knowledgeTermCopy("rag").professional
          } 引用、${knowledgeTermCopy("ocr").professional} 降级和历史复检）`,
        ), copyMode)}
      </a>
    </div>
  );
}
