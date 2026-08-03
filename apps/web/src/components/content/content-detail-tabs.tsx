"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, type ReactElement, type ReactNode } from "react";

import {
  loadContentDetail,
  type ContentDetailData,
} from "@/lib/content-api";
import { ContentDetail } from "@/components/content/content-detail";
import { AnalysisPanel as InteractiveAnalysisPanel } from "@/app/workspaces/[workspaceId]/contents/[contentId]/analysis/analysis-panel";
import { sanitizeReturnTo } from "@/components/workbench/scope-query";
import { useWorkbenchShellContext } from "@/components/workbench/workspace-shell";
import {
  DetailTabs,
  EmptyState,
  ErrorState,
  Panel,
  Skeleton,
  StatusBadge,
} from "@/components/workbench/ui";
import { GuidedPageHeader } from "@/components/workbench/guided-page-header";
import { GuidedPageShell } from "@/components/workbench/guided-page-header";
import { useExperiencePreferences } from "@/components/workbench/experience-preferences-context";
import {
  adoptionStatusCopy,
  analysisConfidenceCopy,
  displayCopy,
  displayText,
  internalReferenceCopy,
  OPERATOR_TERMS,
  preflightOcrCopy,
  providerSummaryCopy,
  riskNodeCopy,
  riskOriginCopy,
  riskRegionCopy,
  riskSeverityCopy,
  riskTypeCopy,
  taskStatusCopy,
  versionValueCopy,
} from "@/components/workbench/operator-display-copy";


export type ContentTab =
  | "overview"
  | "snapshots"
  | "analysis"
  | "risk"
  | "generation";

const TABS = new Set<ContentTab>([
  "overview",
  "snapshots",
  "analysis",
  "risk",
  "generation",
]);

export function normalizeContentTab(value: string | null): ContentTab {
  return value !== null && TABS.has(value as ContentTab)
    ? value as ContentTab
    : "overview";
}

export function safeContentReturnTo(
  workspaceId: string,
  value: string | null | undefined,
): string {
  return sanitizeReturnTo(workspaceId, value)
    ?? `/workspaces/${workspaceId}/contents`;
}

export function canonicalContentDetailQuery(
  workspaceId: string,
  content: ContentDetailData["content"],
  searchParams: Pick<URLSearchParams, "get" | "toString">,
): string {
  const next = new URLSearchParams(searchParams.toString());
  next.set("tab", normalizeContentTab(searchParams.get("tab")));
  next.set(
    "returnTo",
    safeContentReturnTo(workspaceId, searchParams.get("returnTo")),
  );
  next.set("platform", content.platform);
  next.set("account", content.account_id);
  return next.toString();
}

const platformLabel = {
  douyin: "抖音",
  xiaohongshu: "小红书",
} as const;

const lifecycleLabel = {
  draft: "灵感/选题",
  published: "已发布",
  archived: "历史归档",
} as const;

const lifecycleStages = [
  "灵感/选题",
  "AI生成",
  "人工编辑",
  "待审核",
  "已发布",
  "数据采集中",
  "已分析",
  "可复用",
] as const;

function valueText(value: string | number | null): string {
  return value === null ? "缺失" : String(value);
}

function DefinitionList({
  items,
}: {
  items: Array<[string, ReactNode]>;
}): ReactElement {
  return (
    <dl className="grid grid-cols-1 gap-4 text-sm sm:grid-cols-2">
      {items.map(([label, value]) => (
        <div className="rounded-lg bg-slate-50 p-3" key={label}>
          <dt className="text-[var(--text-secondary)]">{label}</dt>
          <dd className="mt-1 font-medium text-[var(--text-primary)]">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function OverviewPanel({
  detail,
  role,
}: {
  detail: ContentDetailData;
  role: "admin" | "editor" | "viewer";
}): ReactElement {
  const { copyMode } = useExperiencePreferences();
  const content = detail.content;
  const cover = content.assets.find((asset) => asset.category === "cover");
  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(260px,1fr)]">
      <Panel title="内容基础信息">
        {cover?.download_url ? (
          <div
            aria-label={`${content.title}封面`}
            className="mb-5 aspect-video rounded-xl bg-cover bg-center"
            role="img"
            style={{ backgroundImage: `url(${cover.download_url})` }}
          />
        ) : (
          <div className="mb-5 flex aspect-video items-center justify-center rounded-xl border border-dashed text-sm text-[var(--text-secondary)]">
            当前记录未提供封面
          </div>
        )}
        <h2 className="text-lg font-semibold">{content.title}</h2>
        <p className="mt-3 whitespace-pre-wrap text-sm leading-7">
          {content.body || "当前记录未提供文案"}
        </p>
      </Panel>
      <Panel title="发布与来源">
        <DefinitionList
          items={[
            ["作品链接", content.work_url
              ? <a className="text-[var(--brand)] underline" href={content.work_url}>打开作品</a>
              : "当前记录未提供"],
            ["发布时间", content.published_at
              ? new Date(content.published_at).toLocaleString("zh-CN")
              : "未发布"],
            ["数据来源", content.platform_content_id
              ? "平台作品记录"
              : "人工录入或导入"],
            ["当前生命周期", lifecycleLabel[content.status]],
            ["发布时目标配置", displayText(internalReferenceCopy(
              content.objective_profile_id,
              "发布时目标配置",
            ), copyMode)],
            ["发布时基准配置", displayText(internalReferenceCopy(
              content.benchmark_profile_id,
              "发布时基准配置",
            ), copyMode)],
            ["当前下一步", content.status === "draft"
              ? "继续人工编辑或进入生成中心"
              : "补充快照并查看分析"],
          ]}
        />
        <div className="mt-5">
          <h3 className="text-sm font-semibold">内容生命周期</h3>
          <ol
            aria-label="内容生命周期"
            className="mt-2 flex flex-wrap items-center gap-2 text-xs"
          >
            {lifecycleStages.map((stage) => {
              const current = detail.lifecycle_stage === stage;
              return (
                <li
                  aria-current={current ? "step" : undefined}
                  className={current
                    ? "rounded-full bg-blue-100 px-3 py-1 font-semibold text-blue-900"
                    : "rounded-full bg-slate-100 px-3 py-1 text-slate-600"}
                  key={stage}
                >
                  {stage}
                </li>
              );
            })}
          </ol>
          {detail.lifecycle_stage === "未知" ? (
            <p className="mt-2 text-xs text-[var(--text-secondary)]">
              历史内容未提供可安全映射的八阶段状态，当前显示为历史归档。
            </p>
          ) : null}
        </div>
      </Panel>
      {role !== "viewer" ? (
        <details className="lg:col-span-2 rounded-xl border bg-white p-5">
          <summary className="cursor-pointer font-semibold">
            编辑、发布、截图与低频操作
          </summary>
          <div className="mt-5 overflow-hidden rounded-xl bg-slate-950">
            <ContentDetail embedded initialContent={content} />
          </div>
        </details>
      ) : null}
    </div>
  );
}

function SnapshotsPanel({
  detail,
  role,
}: {
  detail: ContentDetailData;
  role: "admin" | "editor" | "viewer";
}): ReactElement {
  const { copyMode } = useExperiencePreferences();
  if (!detail.snapshots.length) {
    return (
      <EmptyState
        description={role === "viewer"
          ? "这里还没有数据快照；需要补充或确认时，请联系管理员或编辑者。"
          : "添加并人工确认数据快照后，可查看当前数据；至少两条同口径快照才显示趋势。"}
        title="还没有数据快照"
      />
    );
  }
  const trend = detail.snapshot_trend;
  return (
    <div className="space-y-5">
      <Panel
        description={trend.reason}
        title={displayText({ simple: "快照展示条件", professional: "快照门禁" }, copyMode)}
      >
        <p className="text-sm">
          {trend.eligible
            ? displayText({
                simple: "趋势展示条件已满足；下方时间线仍区分原始记录和统一口径数值。",
                professional: "服务端趋势门禁已满足；下方时间线仍保留原始值与规范化值边界。",
              }, copyMode)
            : "当前只展示数据卡，不生成增长趋势结论。"}
        </p>
        {trend.eligible && trend.metric_key ? (
          <div className="mt-4 overflow-x-auto">
            <table
              aria-label={`${trend.metric_key} 单条内容趋势`}
              className="w-full min-w-[420px] text-left text-sm"
            >
              <thead>
                <tr>
                  <th className="py-2">采集时间</th>
                  <th className="py-2">指标</th>
                  <th className="py-2">规范化值</th>
                </tr>
              </thead>
              <tbody>
                {trend.points.map((point) => (
                  <tr className="border-t" key={point.snapshot_id}>
                    <td className="py-2">
                      {new Date(point.collected_at).toLocaleString("zh-CN")}
                    </td>
                    <td className="py-2">{trend.metric_key}</td>
                    <td className="py-2">{point.normalized_value}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </Panel>
      <ol aria-label="追加式数据快照时间线" className="space-y-4">
        {detail.snapshots.map((snapshot) => (
          <li className="rounded-xl border bg-white p-5" key={snapshot.id}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h3 className="font-semibold">
                  {new Date(snapshot.collected_at).toLocaleString("zh-CN")}
                </h3>
                <p className="mt-1 text-sm text-[var(--text-secondary)]">
                  发布后 {Math.round(snapshot.age_seconds / 3600)} 小时 ·
                  {copyMode === "simple" ? "数据来源已记录" : snapshot.source} · {
                    copyMode === "simple" ? "采集阶段已记录" : snapshot.maturity_bucket
                  }
                </p>
              </div>
              <StatusBadge tone={snapshot.confirmed ? "success" : "warning"}>
                {snapshot.confirmed ? "已人工确认" : "等待人工确认"}
              </StatusBadge>
            </div>
            <div className="mt-4 overflow-x-auto">
              <table className="w-full min-w-[560px] text-left text-sm">
                <thead>
                  <tr className="text-[var(--text-secondary)]">
                    <th className="py-2">指标</th>
                    <th className="py-2">原始值</th>
                    <th className="py-2">{copyMode === "simple" ? "统一口径数值" : "规范化值"}</th>
                    <th className="py-2">{displayText({ simple: "图片文字识别可靠程度", professional: "OCR/识别置信度" }, copyMode)}</th>
                  </tr>
                </thead>
                <tbody>
                  {snapshot.metrics.map((metric) => (
                    <tr className="border-t" key={metric.key}>
                      <td className="py-2">{metric.key}</td>
                      <td className="py-2">{valueText(metric.raw_value)}</td>
                      <td className="py-2">{valueText(metric.normalized_value)}</td>
                      <td className="py-2">
                        {metric.ocr_confidence === null
                          ? "当前记录未提供"
                          : `${Math.round(metric.ocr_confidence * 100)}%`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </li>
        ))}
      </ol>
      <p className="text-sm text-[var(--text-secondary)]">
        图表文本摘要：{trend.eligible
          ? `共有 ${trend.points.length} 条有效同口径快照，按指标 ${
              trend.metric_key
            } 展示趋势。`
          : `${trend.reason} 未绘制趋势图。`}
      </p>
    </div>
  );
}

function GroundedItems({
  title,
  items,
}: {
  title: string;
  items: Array<{
    summary: string;
    confidence: string;
    evidence_ids: string[];
  }>;
}): ReactElement {
  const { copyMode } = useExperiencePreferences();
  return (
    <section>
      <h3 className="font-semibold">{title}</h3>
      {items.length ? (
        <ul className="mt-2 space-y-2">
          {items.map((item, index) => (
            <li className="rounded-lg bg-slate-50 p-3 text-sm" key={`${title}-${index}`}>
              <p>{item.summary}</p>
              <p className="mt-1 text-[var(--text-secondary)]">
                {displayText(OPERATOR_TERMS.confidence, copyMode)} {
                  displayText(analysisConfidenceCopy(item.confidence), copyMode)
                } · {displayText(OPERATOR_TERMS.evidence, copyMode)} {item.evidence_ids.join("、")}
              </p>
            </li>
          ))}
        </ul>
      ) : <p className="mt-2 text-sm">当前记录未提供</p>}
    </section>
  );
}

function AnalysisPanel({
  detail,
}: {
  detail: ContentDetailData;
}): ReactElement {
  const { copyMode } = useExperiencePreferences();
  const run = detail.analysis_runs[0];
  if (!run) {
    return (
      <EmptyState
        description="模型未配置、尚未触发或当前记录没有可读取的分析关系时，不会伪造分析版本和结论。"
        title="当前记录未提供分析结果"
      />
    );
  }
  if (run.status !== "succeeded" || !run.report) {
    return (
      <ErrorState
        description={copyMode === "simple"
          ? `任务状态：${displayText(taskStatusCopy(run.status), copyMode)}；本次分析没有产生可用结果，已保存内容不会受到影响。`
          : `任务状态：${run.status}；安全错误码：${run.error_code ?? "当前记录未提供"}`}
        title={run.status === "failed" ? "分析任务失败" : "分析尚未完成"}
      />
    );
  }
  const report = run.report;
  return (
    <div className="space-y-5">
      <Panel title="数据表现">
        <p>{report.data_performance.summary}</p>
        {report.data_performance.trend_conclusion ? (
          <p className="mt-2 text-sm">{report.data_performance.trend_conclusion}</p>
        ) : null}
        <p className="mt-2 text-sm text-[var(--text-secondary)]">
          {displayText({ simple: "本次判断参考", professional: "Evidence" }, copyMode)}：{report.data_performance.evidence_ids.join("、")}
        </p>
      </Panel>
      <Panel title="问题、原因与行动">
        <div className="space-y-5">
          <GroundedItems items={[
            ...report.title_issues,
            ...report.copy_issues,
            ...report.cover_issues,
          ]} title="发现的问题" />
          <GroundedItems items={report.causal_hypotheses} title="原因假设（非确定因果）" />
          <GroundedItems items={report.recommendations} title="行动建议" />
        </div>
      </Panel>
      <Panel title={copyMode === "simple" ? "判断资料、样本与记录" : "证据、样本与版本"}>
        <DefinitionList
          items={[
            [displayText({ simple: "本次判断参考", professional: "Evidence 引用" }, copyMode), report.evidence.map((item) => item.evidence_id).join("、")],
            ["样本数", run.snapshot_ids.length],
            ["基准范围", displayText(versionValueCopy(run.benchmark_run_id), copyMode)],
            [displayText(OPERATOR_TERMS.confidence, copyMode), displayText(analysisConfidenceCopy(report.confidence), copyMode)],
            ["模型", displayText(providerSummaryCopy(run.model_provider, run.model_version), copyMode)],
            [copyMode === "simple" ? "分析提示记录" : "Prompt 版本", displayText(versionValueCopy(run.prompt_version), copyMode)],
            [copyMode === "simple" ? "分析方法记录" : "分析版本", displayText(versionValueCopy(run.algorithm_version), copyMode)],
            [copyMode === "simple" ? "比较方法记录" : "基准算法版本", displayText(versionValueCopy(run.benchmark_algorithm_version), copyMode)],
            ["反馈", "有用 / 无用（由现有分析操作记录）"],
            ["建议状态", "保存、采用或拒绝状态由现有分析服务控制"],
          ]}
        />
      </Panel>
    </div>
  );
}

function RiskPanel({
  detail,
}: {
  detail: ContentDetailData;
}): ReactElement {
  const { copyMode } = useExperiencePreferences();
  const scans = detail.risk_scans;
  const latest = scans[0];
  if (!latest) {
    return (
      <div className="space-y-4">
        <EmptyState
          description="尚未产生扫描记录；这不是安全通过，仍需人工复核标题、文案和封面。"
          title="尚未扫描"
        />
        <p className="font-semibold">辅助判断，不保证通过平台审核</p>
      </div>
    );
  }
  const assessment = latest.status === "succeeded"
    ? latest
    : scans.find((scan) => scan.status === "succeeded");
  const findings = assessment?.result?.findings ?? [];
  const inProgress = ["queued", "running", "retrying"].includes(latest.status);
  const failed = ["failed", "cancelled"].includes(latest.status);
  return (
    <div className="space-y-5">
      <Panel title="联合扫描状态">
        <DefinitionList
          items={[
            ["扫描节点", displayText(riskNodeCopy(latest.node), copyMode)],
            ["状态", displayText(taskStatusCopy(latest.status), copyMode)],
            [displayText({ simple: "图片文字识别状态", professional: "OCR 状态" }, copyMode), latest.result?.ocr_status
              ? displayText(preflightOcrCopy(latest.result.ocr_status), copyMode)
              : "当前记录未提供"],
            [copyMode === "simple" ? "可用规则资料" : "无有效证据", latest.result?.error_code === "NO_ACTIVE_RISK_EVIDENCE"
              ? copyMode === "simple" ? "没有找到可用规则资料" : "未检索到有效规则"
              : copyMode === "simple" ? "已找到" : "否"],
            [copyMode === "simple" ? "规则记录" : "规则版本", displayText(versionValueCopy(latest.rule_version), copyMode)],
            [copyMode === "simple" ? "判断资料记录" : "证据版本", displayText(versionValueCopy(latest.evidence_version), copyMode)],
            [displayText(OPERATOR_TERMS.embedding, copyMode), copyMode === "simple" ? "已记录" : `${latest.embedding_model_id} / ${latest.embedding_version}`],
            [copyMode === "simple" ? "辅助判断模型" : "RAG 模型", copyMode === "simple" ? "已记录" : latest.rag_model_version],
          ]}
        />
      </Panel>
      {inProgress ? (
        <Panel
          description="保留最近一次成功结果供历史参考；本次复检尚未完成。"
          title="扫描正在进行"
        >
          <p role="status">当前状态：{displayText(taskStatusCopy(latest.status), copyMode)}，请稍后刷新。</p>
        </Panel>
      ) : null}
      {failed ? (
        <ErrorState
          description={{
            simple: "本次风险检查没有完成，不能当作安全通过。请重新检查或联系管理员。",
            professional: `安全错误码：${latest.error_code ?? "RISK_SCAN_FAILED"}；失败结果不会保存为成功扫描。`,
          }}
          title={latest.status === "cancelled" ? "扫描已取消" : "扫描任务失败"}
        />
      ) : null}
      {assessment ? (
        <Panel title={
          assessment.id === latest.id
            ? "风险发现与修改建议"
            : "最近一次成功扫描（历史参考）"
        }>
          {findings.length ? (
          <ul className="space-y-3">
            {findings.map((finding, index) => (
              <li className="rounded-lg border p-4" key={`${finding.risk_type}-${index}`}>
                <div className="flex flex-wrap items-center gap-2">
                  <StatusBadge tone={finding.severity === "high" ? "danger" : "warning"}>
                    {displayText(riskSeverityCopy(finding.severity), copyMode)}
                  </StatusBadge>
                  <strong>{displayText(riskTypeCopy(finding.risk_type), copyMode)}</strong>
                  <span>{displayText(riskOriginCopy(finding.origin), copyMode)}</span>
                </div>
                <p className="mt-2 text-sm">位置：{displayText(riskRegionCopy(finding.region), copyMode)}；命中：{finding.matched_content}</p>
                {finding.ocr_confidence !== null ? (
                  <p className="mt-1 text-sm">
                    {displayText({ simple: "图片文字识别可靠程度", professional: "OCR 置信度" }, copyMode)}：{Math.round((finding.ocr_confidence ?? 0) * 100)}%
                    {finding.requires_human_review
                      ? copyMode === "simple" ? "（可信度较低，必须人工检查）" : "（低置信度，要求人工复核）"
                      : ""}
                  </p>
                ) : null}
                <p className="mt-2 text-sm">原因：{finding.reason}</p>
                <p className="mt-1 text-sm">建议：{finding.suggestion}</p>
                <p className="mt-1 text-sm text-[var(--text-secondary)]">
                  引用：{finding.citations.length
                    ? finding.citations.map((citation) => (
                        `${citation.document_title} ${citation.document_version}`
                      )).join("；")
                    : "无有效引用"}
                </p>
              </li>
            ))}
          </ul>
          ) : assessment.result?.error_code === "NO_ACTIVE_RISK_EVIDENCE" ? (
            <p>{copyMode === "simple"
              ? "没有找到可用规则资料；仅保留固定规则结果，不得视为安全通过。"
              : "RAG 未检索到有效规则；仅保留确定性规则结果，不得视为安全通过。"}</p>
          ) : (
            <p>成功扫描未发现命中；仍不等同于平台官方审核通过。</p>
          )}
        </Panel>
      ) : null}
      <Panel title="历史扫描与复检">
        <ol className="space-y-2 text-sm">
          {scans.map((item) => (
            <li key={item.id}>
              {new Date(item.created_at).toLocaleString("zh-CN")} · {displayText(taskStatusCopy(item.status), copyMode)}
              {item.previous_scan_id
                ? ` · ${displayText(displayCopy(
                    internalReferenceCopy(
                      item.previous_scan_id,
                      "复检来源",
                    ).simple,
                    `复检自 ${item.previous_scan_id}`,
                  ), copyMode)}`
                : " · 首次扫描"}
            </li>
          ))}
        </ol>
      </Panel>
      <p className="font-semibold">
        {assessment?.result?.disclaimer ?? "辅助判断，不保证通过平台审核"}
      </p>
    </div>
  );
}

function GenerationPanel({
  detail,
}: {
  detail: ContentDetailData;
}): ReactElement {
  const { copyMode } = useExperiencePreferences();
  if (!detail.generation_records.length) {
    return (
      <EmptyState
        description="现有记录没有与本内容安全关联的生成任务；不会猜测模型、风格、事实或采用关系。"
        title="当前记录未提供生成关系"
      />
    );
  }
  return (
    <div className="space-y-4">
      {detail.generation_records.map((record) => (
        <Panel
          key={record.id}
          title={`封面生成任务 · ${displayText(taskStatusCopy(record.status), copyMode)}`}
        >
          <DefinitionList
            items={[
              [displayText({ simple: "模型服务与费用说明", professional: "Provider 与模型安全状态" }, copyMode), displayText(providerSummaryCopy(record.provider, record.model_id), copyMode)],
              [copyMode === "simple" ? "生成规则记录" : "生成合同版本", displayText(versionValueCopy(record.contract_version), copyMode)],
              [copyMode === "simple" ? "账号风格记录" : "账号风格版本", displayText(versionValueCopy(record.account_style_version), copyMode)],
              [copyMode === "simple" ? "栏目规则记录" : "栏目覆盖版本", displayText(versionValueCopy(record.column_override_version), copyMode)],
              [copyMode === "simple" ? "事实资料确认记录" : "事实来源与确认状态", displayText(versionValueCopy(record.confirmed_facts_version), copyMode)],
              ["爆款引用", record.viral_reference_count ?? "当前记录未提供"],
              [copyMode === "simple" ? "生成设置记录" : "生成预设版本", displayText(versionValueCopy(record.preset_version), copyMode)],
              ["原始生成结果", record.original_result ?? "当前记录未提供"],
              ["最终采用结果", record.final_result ?? "当前记录未提供"],
              ["采用状态", displayText(adoptionStatusCopy(record.adoption_status), copyMode)],
              ["修改幅度", record.modification_magnitude ?? "当前记录未提供"],
            ]}
          />
        </Panel>
      ))}
    </div>
  );
}

export function ContentDetailTabs({
  activeTab,
  detail,
  onTabChange,
  returnTo,
  role,
}: {
  activeTab: ContentTab;
  detail: ContentDetailData;
  onTabChange: (tab: ContentTab) => void;
  returnTo?: string;
  role: "admin" | "editor" | "viewer";
}): ReactElement {
  const content = detail.content;
  const safeReturn = safeContentReturnTo(content.workspace_id, returnTo);
  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <nav aria-label="内容返回路径">
        <Link className="text-sm font-semibold text-[var(--brand)]" href={safeReturn}>
          返回内容库
        </Link>
      </nav>
      <GuidedPageHeader
        context={[
          platformLabel[content.platform],
          content.account_name,
          content.column_campaign_name ?? "账号默认",
          lifecycleLabel[content.status],
        ].join(" · ")}
        pageId="contentDetail"
        primaryAction={role === "viewer" ? undefined : (
          <Link
            className="rounded-lg bg-[var(--brand)] px-4 py-2 text-sm font-semibold text-white"
            href={
              `/workspaces/${content.workspace_id}/generation?platform=${content.platform}`
              + `&account=${content.account_id}&returnTo=${encodeURIComponent(safeReturn)}`
            }
          >
            生成同类内容
          </Link>
        )}
        title={content.title}
      />
      <DetailTabs
        activeTab={activeTab}
        ariaLabel="内容详情"
        onTabChange={(tab) => onTabChange(tab as ContentTab)}
        tabs={[
          {
            id: "overview",
            label: "概览",
            panel: <OverviewPanel detail={detail} role={role} />,
          },
          { id: "snapshots", label: "数据快照", panel: <SnapshotsPanel detail={detail} role={role} /> },
          {
            id: "analysis",
            label: "分析",
            panel: (
              <div className="space-y-6">
                <AnalysisPanel detail={detail} />
                {role !== "viewer" ? (
                  <Panel
                    description="启动分析、提交有用性反馈，并保存或采用服务端返回的建议。"
                    title="分析操作"
                  >
                    <InteractiveAnalysisPanel
                      contentId={content.id}
                      workspaceId={content.workspace_id}
                    />
                  </Panel>
                ) : null}
              </div>
            ),
          },
          { id: "risk", label: "风控", panel: <RiskPanel detail={detail} /> },
          { id: "generation", label: "生成记录", panel: <GenerationPanel detail={detail} /> },
        ]}
      />
    </div>
  );
}

type LoaderState =
  | { status: "loading" }
  | { status: "ready"; detail: ContentDetailData }
  | { status: "failed"; message: string };

export function ContentDetailPage({
  workspaceId,
  contentId,
}: {
  workspaceId: string;
  contentId: string;
}): ReactElement {
  const context = useWorkbenchShellContext();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const router = useRouter();
  const [state, setState] = useState<LoaderState>({ status: "loading" });
  const searchKey = searchParams.toString();

  useEffect(() => {
    const controller = new AbortController();
    loadContentDetail(workspaceId, contentId, controller.signal)
      .then((detail) => setState({ status: "ready", detail }))
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) {
          setState({
            status: "failed",
            message: caught instanceof Error ? caught.message : "内容详情加载失败",
          });
        }
      });
    return () => controller.abort();
  }, [contentId, workspaceId]);

  useEffect(() => {
    if (state.status !== "ready") return;
    const canonical = canonicalContentDetailQuery(
      workspaceId,
      state.detail.content,
      new URLSearchParams(searchKey),
    );
    if (canonical !== searchKey) {
      router.replace(`${pathname}?${canonical}`);
    }
  }, [pathname, router, searchKey, state, workspaceId]);

  if (!context || state.status === "loading") {
    return (
      <GuidedPageShell pageId="contentDetail">
        <Skeleton label="正在加载内容详情" />
      </GuidedPageShell>
    );
  }
  if (state.status === "failed") {
    return (
      <GuidedPageShell pageId="contentDetail">
        <ErrorState
          description="内容详情暂时无法读取；已保存内容不会受到影响。"
          title="内容详情加载失败"
        />
      </GuidedPageShell>
    );
  }
  const activeTab = normalizeContentTab(searchParams.get("tab"));
  const returnTo = safeContentReturnTo(
    workspaceId,
    searchParams.get("returnTo"),
  );
  return (
    <ContentDetailTabs
      activeTab={activeTab}
      detail={state.detail}
      onTabChange={(tab) => {
        const next = new URLSearchParams(searchKey);
        next.set("tab", tab);
        router.replace(
          `${pathname}?${canonicalContentDetailQuery(
            workspaceId,
            state.detail.content,
            next,
          )}`,
        );
      }}
      returnTo={returnTo}
      role={context.role}
    />
  );
}
