"use client";

import Link from "next/link";
import { useEffect, useState, type ReactElement } from "react";

import {
  type AccountDashboardData,
  DashboardApiError,
  dashboardDrillDownHref,
  loadAccountDashboard,
} from "@/lib/dashboard-api";
import {
  EmptyState,
  ErrorState,
  Panel,
  PermissionNotice,
  Skeleton,
  StatusBadge,
} from "@/components/workbench/ui";
import { GuidedPageHeader } from "@/components/workbench/guided-page-header";
import { useWorkbenchShellContext } from "@/components/workbench/workspace-shell";

import { ChartPanel } from "./chart-panel";


const formatNumber = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 });
type OptionalDashboardModule = "benchmarks" | "trend" | "attention";
const OPTIONAL_MODULES = new Set<OptionalDashboardModule>([
  "benchmarks",
  "trend",
  "attention",
]);

function dashboardPreferenceKey(memberId: string, accountId: string): string {
  return `operations-ai:dashboard-layout:${memberId}:${accountId}`;
}

export function readDashboardModulePreferences(
  storage: Pick<Storage, "getItem">,
  memberId: string,
  accountId: string,
): OptionalDashboardModule[] {
  const raw = storage.getItem(dashboardPreferenceKey(memberId, accountId));
  if (!raw) return [];
  try {
    const value: unknown = JSON.parse(raw);
    if (!Array.isArray(value)) return [];
    return value.filter(
      (item): item is OptionalDashboardModule =>
        typeof item === "string"
        && OPTIONAL_MODULES.has(item as OptionalDashboardModule),
    );
  } catch {
    return [];
  }
}

function writeDashboardModulePreferences(
  storage: Pick<Storage, "setItem">,
  memberId: string,
  accountId: string,
  hidden: OptionalDashboardModule[],
): void {
  storage.setItem(
    dashboardPreferenceKey(memberId, accountId),
    JSON.stringify([...new Set(hidden)].sort()),
  );
}

function confidenceLabel(
  confidence: AccountDashboardData["confidence"],
): string {
  return {
    raw_only: "仅原始值",
    low_confidence: "低置信度",
    normal: "正常置信度",
  }[confidence];
}

function contentTypeLabel(
  contentType: AccountDashboardData["content_type"],
): string {
  return contentType === "video" ? "视频" : "图文";
}

function platformLabel(
  platform: AccountDashboardData["platform"],
): string {
  return platform === "douyin" ? "抖音" : "小红书";
}

export function AccountDashboard({
  workspaceId,
  accountId,
  memberId,
  initialContentType = "image_text",
  initialMaturityBucket = "24h",
}: {
  workspaceId: string;
  accountId: string;
  memberId?: string;
  initialContentType?: "video" | "image_text";
  initialMaturityBucket?: "1h" | "24h" | "72h" | "7d";
}): ReactElement {
  const shellContext = useWorkbenchShellContext();
  const preferenceMemberId = memberId ?? shellContext?.member_id;
  const [dashboard, setDashboard] = useState<AccountDashboardData | null>(null);
  const [requestState, setRequestState] = useState<"loading" | "ready" | "failed" | "permission">("loading");
  const [contentType, setContentType] = useState(initialContentType);
  const [maturityBucket, setMaturityBucket] = useState(initialMaturityBucket);
  const [hiddenModules, setHiddenModules] = useState<OptionalDashboardModule[]>(
    () => (
      preferenceMemberId && typeof window !== "undefined"
        ? readDashboardModulePreferences(
          window.localStorage,
          preferenceMemberId,
          accountId,
        )
        : []
    ),
  );

  useEffect(() => {
    let active = true;
    loadAccountDashboard(workspaceId, accountId, contentType, maturityBucket)
      .then((data) => {
        if (!active) return;
        setDashboard(data);
        setRequestState("ready");
      })
      .catch((caught: unknown) => {
        if (!active) return;
        setRequestState(
          caught instanceof DashboardApiError && caught.status === 403
            ? "permission"
            : "failed",
        );
      });
    return () => { active = false; };
  }, [accountId, contentType, maturityBucket, workspaceId]);

  function updateScope(
    nextContentType: "video" | "image_text",
    nextMaturityBucket: "1h" | "24h" | "72h" | "7d",
  ) {
    setContentType(nextContentType);
    setMaturityBucket(nextMaturityBucket);
    const query = new URLSearchParams(window.location.search);
    query.set("content_type", nextContentType);
    query.set("maturity_bucket", nextMaturityBucket);
    window.history.replaceState(null, "", `?${query}`);
  }

  function setModuleHidden(
    module: OptionalDashboardModule,
    hidden: boolean,
  ) {
    const next = hidden
      ? [...new Set([...hiddenModules, module])]
      : hiddenModules.filter((item) => item !== module);
    setHiddenModules(next);
    if (preferenceMemberId) {
      writeDashboardModulePreferences(
        window.localStorage,
        preferenceMemberId,
        accountId,
        next,
      );
    }
  }

  function restoreDefaultLayout() {
    setHiddenModules([]);
    if (preferenceMemberId) {
      writeDashboardModulePreferences(
        window.localStorage,
        preferenceMemberId,
        accountId,
        [],
      );
    }
  }

  if (requestState === "loading") return <Skeleton label="正在加载账号仪表盘" />;
  if (requestState === "permission") {
    return <PermissionNotice currentRole="当前成员" requiredRole="工作区查看者" />;
  }
  if (requestState === "failed" || !dashboard) {
    return (
      <ErrorState
        description="无法读取账号指标。筛选范围和已保存数据不会丢失。"
        title="账号仪表盘加载失败"
      />
    );
  }
  if (!dashboard.goal_cards.length) {
    return (
      <EmptyState
        description="请先确认同平台、同账号、同内容类型的运营快照。"
        title="暂无可展示指标"
      />
    );
  }

  const hidden = new Set(hiddenModules);
  const primaryTrend = dashboard.charts.find((chart) => chart.kind === "line");
  const funnelChart = dashboard.charts.find((chart) => chart.kind === "funnel");
  const heatmapChart = dashboard.charts.find((chart) => chart.kind === "heatmap");
  const ineligibleGates = dashboard.chart_gates.filter((gate) => !gate.eligible);

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <GuidedPageHeader
        context={{
          simple: "数据按当前作品类型和数据采集时间分别计算。",
          professional: dashboard.explanation,
        }}
        pageId="accountDashboard"
        secondaryActions={(
          <button
            className="rounded-lg border bg-white px-3 py-2 text-sm font-semibold"
            onClick={restoreDefaultLayout}
            type="button"
          >
            恢复默认布局
          </button>
        )}
        title={dashboard.account_name}
      />

      <section aria-label="账号范围" className="rounded-xl border bg-white p-5">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge tone={dashboard.platform === "douyin" ? "info" : "warning"}>
            {platformLabel(dashboard.platform)}
          </StatusBadge>
          <StatusBadge tone={dashboard.confidence === "normal" ? "success" : "warning"}>
            {confidenceLabel(dashboard.confidence)}
          </StatusBadge>
        </div>
        <dl className="mt-4 grid grid-cols-2 gap-4 text-sm md:grid-cols-6">
          <div><dt className="text-[var(--text-secondary)]">账号</dt><dd className="font-semibold">{dashboard.account_name}</dd></div>
          <div><dt className="text-[var(--text-secondary)]">内容类型</dt><dd className="font-semibold">{contentTypeLabel(dashboard.content_type)}</dd></div>
          <div><dt className="text-[var(--text-secondary)]">数据成熟度</dt><dd className="font-semibold">{dashboard.maturity_bucket}</dd></div>
          <div><dt className="text-[var(--text-secondary)]">基准范围</dt><dd className="font-semibold">最近 {dashboard.benchmark_sample_size} 条</dd></div>
          <div><dt className="text-[var(--text-secondary)]">实际样本</dt><dd className="font-semibold">实际样本 {dashboard.sample_count} 条</dd></div>
          <div><dt className="text-[var(--text-secondary)]">数据完整度</dt><dd className="font-semibold">{Math.round(dashboard.data_completeness * 100)}%</dd></div>
        </dl>
        <p className="mt-3 text-sm text-[var(--text-secondary)]">
          基准范围：最近 {dashboard.benchmark_sample_size} 条同口径内容
        </p>
        <div className="mt-4 grid grid-cols-2 gap-3 text-sm sm:w-fit">
          <label>
            内容类型
            <select
              className="mt-1 block min-h-10 w-full rounded-lg border bg-white px-3"
              onChange={(event) => updateScope(
                event.target.value as "video" | "image_text",
                maturityBucket,
              )}
              value={contentType}
            >
              <option value="image_text">图文</option>
              <option value="video">视频</option>
            </select>
          </label>
          <label>
            成熟度
            <select
              className="mt-1 block min-h-10 w-full rounded-lg border bg-white px-3"
              onChange={(event) => updateScope(
                contentType,
                event.target.value as "1h" | "24h" | "72h" | "7d",
              )}
              value={maturityBucket}
            >
              <option value="1h">1h</option>
              <option value="24h">24h</option>
              <option value="72h">72h</option>
              <option value="7d">7d</option>
            </select>
          </label>
        </div>
      </section>

      <section aria-labelledby="target-metrics">
        <h2 className="text-lg font-semibold" id="target-metrics">目标指标</h2>
        <div className="mt-3 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {dashboard.goal_cards.slice(0, 6).map((card) => (
            <Link
              className="rounded-xl border bg-white p-5 hover:border-[var(--brand)]"
              href={dashboardDrillDownHref(card.drill_down_filter)}
              key={card.metric_key}
            >
              <p className="text-sm text-[var(--text-secondary)]">{card.label}</p>
              <p className="mt-2 text-2xl font-semibold">
                {card.current_value === null ? "—" : formatNumber.format(card.current_value)}
              </p>
              <div className="mt-3 flex flex-wrap gap-2 text-xs text-[var(--text-secondary)]">
                <span>变化 {card.change_rate === null ? "—" : `${formatNumber.format(card.change_rate * 100)}%`}</span>
                <span>分位 {card.historical_percentile === null ? "样本不足" : `${formatNumber.format(card.historical_percentile * 100)}%`}</span>
                <span>完整度 {formatNumber.format(card.data_completeness * 100)}%</span>
              </div>
              <p className="mt-3 text-xs text-[var(--text-secondary)]">{card.explanation}</p>
            </Link>
          ))}
        </div>
      </section>

      {!hidden.has("trend") && primaryTrend ? (
        <Panel
          title="数据趋势"
          description="仅展示一个同量纲、满足服务端门禁的主要趋势。"
        >
          <button
            aria-label="隐藏数据趋势"
            className="mb-3 text-sm text-[var(--brand)]"
            onClick={() => setModuleHidden("trend", true)}
            type="button"
          >
            隐藏此模块
          </button>
          <ChartPanel chart={primaryTrend} />
        </Panel>
      ) : null}

      {funnelChart ? (
        <Panel
          description="仅在服务端确认漏斗必要字段完整且样本达标后展示。"
          title="漏斗分析"
        >
          <ChartPanel chart={funnelChart} />
        </Panel>
      ) : null}

      {heatmapChart ? (
        <Panel
          description="仅在服务端确认发布时间样本达标后展示。"
          title="发布时间热力图"
        >
          <ChartPanel chart={heatmapChart} />
        </Panel>
      ) : null}

      {ineligibleGates.length ? (
        <Panel title="图表暂不可用" description="以下原因由 API 门禁返回，前端不重新计算。">
          <ul className="space-y-2 text-sm">
            {ineligibleGates.map((gate) => (
              <li className="rounded-lg bg-slate-50 p-3" key={gate.kind}>
                <strong>{gate.kind === "line" ? "趋势图" : gate.kind === "funnel" ? "漏斗图" : "发布时间热力图"}：</strong>
                {gate.reason}
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}

      {!hidden.has("benchmarks") && dashboard.benchmark_bands.length ? (
        <Panel title="基准区间">
          <button
            aria-label="隐藏基准区间"
            className="mb-3 text-sm text-[var(--brand)]"
            onClick={() => setModuleHidden("benchmarks", true)}
            type="button"
          >
            隐藏此模块
          </button>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {dashboard.benchmark_bands.map((band) => (
              <article className="rounded-lg border p-4" key={band.metric_key}>
                <h3 className="font-semibold">{band.label}</h3>
                <p className="mt-2">中位数 {formatNumber.format(band.median)}</p>
                <p>前 25% {formatNumber.format(band.top_25)}</p>
                <p>前 10% {formatNumber.format(band.top_10)}</p>
                <p className="mt-2 text-xs text-[var(--text-secondary)]">
                  有效样本 {band.sample_count} 条 · 单位 {band.unit}
                </p>
              </article>
            ))}
          </div>
        </Panel>
      ) : null}

      {!hidden.has("attention") ? (
        <Panel title="值得关注" description="爆款候选、异常内容及原因假设均保留置信度说明。">
          <button
            aria-label="隐藏候选与异常"
            className="mb-3 text-sm text-[var(--brand)]"
            onClick={() => setModuleHidden("attention", true)}
            type="button"
          >
            隐藏此模块
          </button>
          {dashboard.attention_items.length ? (
            <ul className="space-y-3">
              {dashboard.attention_items.map((item) => (
                <li className="rounded-lg border p-4" key={`${item.kind}:${item.content_id}`}>
                  <StatusBadge tone={item.kind === "candidate" ? "success" : "warning"}>
                    {item.kind === "candidate" ? "爆款候选" : "异常内容"}
                  </StatusBadge>
                  <Link className="mt-2 block font-semibold text-[var(--brand)]" href={dashboardDrillDownHref(item.drill_down_filter)}>
                    {item.title}
                  </Link>
                  <p className="mt-1 text-sm">{item.reason}</p>
                  <p className="mt-1 text-xs text-[var(--text-secondary)]">
                    原因假设 · {confidenceLabel(dashboard.confidence)}，不代表确定因果
                  </p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-[var(--text-secondary)]">当前没有满足服务端候选或异常门禁的内容。</p>
          )}
        </Panel>
      ) : null}

      <Panel title="下一步行动" description="状态、风险和关键行动不会被展示偏好隐藏。">
        <ol className="space-y-2">
          {dashboard.next_actions.map((action, index) => (
            <li className="flex gap-3" key={action}>
              <span className="font-semibold text-[var(--brand)]">{index + 1}.</span>
              <span>{action}</span>
            </li>
          ))}
        </ol>
      </Panel>
    </div>
  );
}
