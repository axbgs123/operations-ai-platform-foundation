"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  useEffect,
  useMemo,
  useState,
  type ReactElement,
} from "react";

import type { WorkbenchAccount } from "@/components/workbench/scope-query";
import { useWorkbenchShellContext } from "@/components/workbench/workspace-shell";
import {
  DataTableFrame,
  EmptyState,
  ErrorState,
  PageHeader,
  Skeleton,
  StatusBadge,
} from "@/components/workbench/ui";
import {
  loadAnalysisQueue,
  type AnalysisQueuePageData,
} from "@/lib/analysis-api";


export type AnalysisQueueFilters = {
  platform?: "douyin" | "xiaohongshu";
  account?: string;
  status?:
    | "pending"
    | "running"
    | "completed"
    | "insufficient_sample"
    | "failed"
    | "configuration_required"
    | "suggestion_pending";
  sort: "newest" | "oldest";
  page: number;
};

const PLATFORMS = new Set(["douyin", "xiaohongshu"]);
const STATUSES = new Set([
  "pending",
  "running",
  "completed",
  "insufficient_sample",
  "failed",
  "configuration_required",
  "suggestion_pending",
]);
const SORTS = new Set(["newest", "oldest"]);

function valid<T extends string>(
  value: string | null,
  allowed: Set<string>,
): T | undefined {
  return value !== null && allowed.has(value) ? value as T : undefined;
}

export function normalizeAnalysisQueueFilters(
  searchParams: Pick<URLSearchParams, "get">,
  accounts: readonly WorkbenchAccount[],
): AnalysisQueueFilters {
  const rawPlatform = searchParams.get("platform");
  if (rawPlatform !== null && !PLATFORMS.has(rawPlatform)) {
    return {
      platform: undefined,
      account: undefined,
      status: undefined,
      sort: "newest",
      page: 1,
    };
  }
  const platform = valid<NonNullable<AnalysisQueueFilters["platform"]>>(
    rawPlatform,
    PLATFORMS,
  );
  const accountCandidate = accounts.find(
    (account) => account.account_id === searchParams.get("account"),
  );
  const account = accountCandidate
    && platform
    && accountCandidate.platform === platform
    ? accountCandidate.account_id
    : undefined;
  const rawPage = Number(searchParams.get("page") ?? "1");
  return {
    platform,
    account,
    status: valid<NonNullable<AnalysisQueueFilters["status"]>>(
      searchParams.get("status"),
      STATUSES,
    ),
    sort: valid<AnalysisQueueFilters["sort"]>(
      searchParams.get("sort"),
      SORTS,
    ) ?? "newest",
    page: Number.isSafeInteger(rawPage) && rawPage > 0 ? rawPage : 1,
  };
}

export function updateAnalysisQueueFilters(
  current: AnalysisQueueFilters,
  change: Partial<AnalysisQueueFilters>,
): AnalysisQueueFilters {
  const next = { ...current, ...change, page: 1 };
  if (
    Object.hasOwn(change, "platform")
    && change.platform !== current.platform
  ) {
    next.account = undefined;
  }
  if (Object.hasOwn(change, "page")) next.page = change.page ?? 1;
  return next;
}

export function analysisQueueFiltersQuery(
  filters: AnalysisQueueFilters,
): string {
  const query = new URLSearchParams();
  if (filters.platform) query.set("platform", filters.platform);
  if (filters.account) query.set("account", filters.account);
  if (filters.status) query.set("status", filters.status);
  query.set("sort", filters.sort);
  query.set("page", String(filters.page));
  return query.toString();
}

const platformLabel = {
  douyin: "抖音",
  xiaohongshu: "小红书",
} as const;

const statusLabel = {
  pending: "待分析",
  running: "分析中",
  completed: "已完成",
  insufficient_sample: "样本不足",
  failed: "失败",
  configuration_required: "需要配置",
  suggestion_pending: "建议待采用",
} as const;

function statusTone(
  status: keyof typeof statusLabel,
): "neutral" | "info" | "success" | "warning" | "danger" {
  if (status === "failed") return "danger";
  if (
    status === "insufficient_sample"
    || status === "configuration_required"
    || status === "suggestion_pending"
  ) return "warning";
  if (status === "completed") return "success";
  if (status === "running") return "info";
  return "neutral";
}

function returnTo(
  workspaceId: string,
  filters: AnalysisQueueFilters,
): string {
  return (
    `/workspaces/${workspaceId}/analysis?${analysisQueueFiltersQuery(filters)}`
  );
}

function detailHref(
  workspaceId: string,
  contentId: string,
  filters: AnalysisQueueFilters,
): string {
  const query = new URLSearchParams({
    tab: "analysis",
    returnTo: returnTo(workspaceId, filters),
  });
  if (filters.platform) query.set("platform", filters.platform);
  if (filters.account) query.set("account", filters.account);
  return `/workspaces/${workspaceId}/contents/${contentId}?${query}`;
}

function EvidenceState({
  status,
}: {
  status: AnalysisQueuePageData["items"][number]["evidence_status"];
}): ReactElement {
  if (status === "available") return <span>Evidence 已记录</span>;
  if (status === "insufficient_sample") return <span>Evidence 有限，样本不足</span>;
  return <span>无有效 Evidence</span>;
}

export function AnalysisQueue({
  accounts,
  data,
  filters,
  onFiltersChange,
  workspaceId,
}: {
  accounts: WorkbenchAccount[];
  data: AnalysisQueuePageData;
  filters: AnalysisQueueFilters;
  onFiltersChange: (filters: AnalysisQueueFilters) => void;
  role: "admin" | "editor" | "viewer";
  workspaceId: string;
}): ReactElement {
  const visibleAccounts = accounts.filter(
    (account) => account.platform === filters.platform,
  );
  const change = (changeSet: Partial<AnalysisQueueFilters>) => {
    onFiltersChange(updateAnalysisQueueFilters(filters, changeSet));
  };
  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <PageHeader
        description="队列只展示服务端已经确认的分析状态、样本、Evidence 和置信度；不同平台分别筛选。"
        title="分析中心"
      />
      <section
        aria-label="分析队列筛选"
        className="grid gap-3 rounded-xl border bg-white p-4 sm:grid-cols-2 lg:grid-cols-4"
      >
        <label className="text-sm font-medium">
          平台
          <select
            className="mt-1 min-h-10 w-full rounded-lg border bg-white px-3"
            onChange={(event) => change({
              platform: event.target.value
                ? event.target.value as AnalysisQueueFilters["platform"]
                : undefined,
            })}
            value={filters.platform ?? ""}
          >
            <option value="">请选择平台</option>
            <option value="douyin">抖音</option>
            <option value="xiaohongshu">小红书</option>
          </select>
        </label>
        <label className="text-sm font-medium">
          账号
          <select
            className="mt-1 min-h-10 w-full rounded-lg border bg-white px-3"
            disabled={!filters.platform}
            onChange={(event) => change({
              account: event.target.value || undefined,
            })}
            value={filters.account ?? ""}
          >
            <option value="">全部账号</option>
            {visibleAccounts.map((account) => (
              <option key={account.account_id} value={account.account_id}>
                {account.name}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm font-medium">
          分析状态
          <select
            className="mt-1 min-h-10 w-full rounded-lg border bg-white px-3"
            onChange={(event) => change({
              status: event.target.value
                ? event.target.value as AnalysisQueueFilters["status"]
                : undefined,
            })}
            value={filters.status ?? ""}
          >
            <option value="">全部状态</option>
            {Object.entries(statusLabel).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </label>
        <label className="text-sm font-medium">
          排序
          <select
            className="mt-1 min-h-10 w-full rounded-lg border bg-white px-3"
            onChange={(event) => change({
              sort: event.target.value as AnalysisQueueFilters["sort"],
            })}
            value={filters.sort}
          >
            <option value="newest">最新内容优先</option>
            <option value="oldest">最早内容优先</option>
          </select>
        </label>
      </section>
      {!filters.platform ? (
        <EmptyState
          description="请选择抖音或小红书。分析状态不会跨平台混合排序。"
          title="请先选择平台"
        />
      ) : !data.items.length ? (
        <EmptyState
          description="调整状态或账号范围后重试。"
          title="当前范围没有分析事项"
        />
      ) : (
        <>
          <DataTableFrame label="分析队列桌面列表">
            <table className="hidden min-w-[1180px] w-full text-left text-sm md:table">
              <thead className="bg-slate-50 text-[var(--text-secondary)]">
                <tr>
                  {[
                    "内容",
                    "范围",
                    "栏目",
                    "类型",
                    "成熟度",
                    "样本",
                    "版本",
                    "当前问题",
                    "置信度/Evidence",
                    "建议",
                    "下一步",
                  ].map((label) => (
                    <th className="px-3 py-3" key={label}>{label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr className="border-t" key={item.content_id}>
                    <td className="max-w-56 px-3 py-3">
                      <StatusBadge tone={statusTone(item.status)}>
                        {statusLabel[item.status]}
                      </StatusBadge>
                      <p className="mt-2">{item.safe_summary}</p>
                    </td>
                    <td className="px-3 py-3">
                      {platformLabel[item.platform]} · {item.account_name}
                    </td>
                    <td className="px-3 py-3">
                      {item.column_campaign_name ?? "账号默认"}
                    </td>
                    <td className="px-3 py-3">
                      {item.content_type === "video" ? "视频" : "图文"}
                    </td>
                    <td className="px-3 py-3">{item.maturity ?? "暂无快照"}</td>
                    <td className="px-3 py-3">{item.sample_count}</td>
                    <td className="px-3 py-3">
                      {item.analysis_version ?? "尚未生成"}
                    </td>
                    <td className="max-w-64 px-3 py-3">{item.safe_summary}</td>
                    <td className="px-3 py-3">
                      <p>{item.confidence === "unknown" ? "未提供" : item.confidence}</p>
                      <EvidenceState status={item.evidence_status} />
                    </td>
                    <td className="px-3 py-3">
                      {item.suggestion_status === "saved"
                        ? "等待采用或拒绝"
                        : item.suggestion_status === "none"
                          ? "暂无"
                          : item.suggestion_status}
                    </td>
                    <td className="px-3 py-3">
                      <Link
                        className="font-semibold text-[var(--brand)]"
                        href={detailHref(workspaceId, item.content_id, filters)}
                      >
                        查看分析
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </DataTableFrame>
          <ul
            aria-label="分析队列移动卡片"
            className="grid grid-cols-1 gap-3 md:hidden"
          >
            {data.items.map((item) => (
              <li className="rounded-xl border bg-white p-4" key={item.content_id}>
                <div className="flex items-start justify-between gap-3">
                  <p className="font-semibold">{item.safe_summary}</p>
                  <StatusBadge tone={statusTone(item.status)}>
                    {statusLabel[item.status]}
                  </StatusBadge>
                </div>
                <p className="mt-2 text-sm text-[var(--text-secondary)]">
                  {platformLabel[item.platform]} · {item.account_name}
                </p>
                <dl className="mt-3 grid grid-cols-2 gap-3 text-sm">
                  <div><dt>成熟度</dt><dd>{item.maturity ?? "暂无快照"}</dd></div>
                  <div><dt>样本数</dt><dd>{item.sample_count}</dd></div>
                  <div><dt>置信度</dt><dd>{item.confidence}</dd></div>
                  <div><dt>Evidence</dt><dd><EvidenceState status={item.evidence_status} /></dd></div>
                </dl>
                <Link
                  className="mt-4 inline-flex font-semibold text-[var(--brand)]"
                  href={detailHref(workspaceId, item.content_id, filters)}
                >
                  查看分析
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}
      {data.pages > 1 ? (
        <nav aria-label="分析队列分页" className="flex items-center justify-between">
          <button
            className="rounded-lg border bg-white px-3 py-2 disabled:opacity-50"
            disabled={data.page <= 1}
            onClick={() => onFiltersChange({ ...filters, page: data.page - 1 })}
            type="button"
          >
            上一页
          </button>
          <span>第 {data.page} / {data.pages} 页，共 {data.total} 条</span>
          <button
            className="rounded-lg border bg-white px-3 py-2 disabled:opacity-50"
            disabled={data.page >= data.pages}
            onClick={() => onFiltersChange({ ...filters, page: data.page + 1 })}
            type="button"
          >
            下一页
          </button>
        </nav>
      ) : null}
    </div>
  );
}

type QueueState =
  | { status: "idle" }
  | { status: "ready"; data: AnalysisQueuePageData; queryKey: string }
  | { status: "failed"; message: string; queryKey: string };

function emptyData(
  filters: AnalysisQueueFilters,
): AnalysisQueuePageData {
  return {
    platform: filters.platform ?? "douyin",
    account_id: filters.account ?? null,
    status: filters.status ?? null,
    sort: filters.sort,
    page: filters.page,
    page_size: 20,
    total: 0,
    pages: 0,
    items: [],
  };
}

export function AnalysisQueuePage({
  workspaceId,
}: {
  workspaceId: string;
}): ReactElement {
  const context = useWorkbenchShellContext();
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const accounts = useMemo(() => context?.accounts ?? [], [context?.accounts]);
  const searchKey = searchParams.toString();
  const filters = normalizeAnalysisQueueFilters(
    new URLSearchParams(searchKey),
    accounts,
  );
  const [state, setState] = useState<QueueState>({ status: "idle" });

  useEffect(() => {
    if (!filters.platform) return;
    const controller = new AbortController();
    loadAnalysisQueue(
      workspaceId,
      {
        platform: filters.platform,
        account_id: filters.account,
        status: filters.status,
        page: filters.page,
        page_size: 20,
        sort: filters.sort,
      },
      controller.signal,
    )
      .then((data) => setState({ status: "ready", data, queryKey: searchKey }))
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) {
          setState({
            status: "failed",
            queryKey: searchKey,
            message: caught instanceof Error
              ? caught.message
              : "分析队列加载失败",
          });
        }
      });
    return () => controller.abort();
  }, [
    filters.account,
    filters.page,
    filters.platform,
    filters.sort,
    filters.status,
    searchKey,
    workspaceId,
  ]);

  if (!context) return <Skeleton label="正在加载分析中心" />;
  if (
    filters.platform
    && (state.status === "idle" || state.queryKey !== searchKey)
  ) {
    return <Skeleton label="正在加载分析队列" />;
  }
  if (state.status === "failed" && state.queryKey === searchKey) {
    return <ErrorState description={state.message} title="分析队列加载失败" />;
  }
  const data = state.status === "ready" && state.queryKey === searchKey
    ? state.data
    : emptyData(filters);
  return (
    <AnalysisQueue
      accounts={accounts}
      data={data}
      filters={filters}
      onFiltersChange={(next) => {
        router.push(`${pathname}?${analysisQueueFiltersQuery(next)}`);
      }}
      role={context.role}
      workspaceId={workspaceId}
    />
  );
}
