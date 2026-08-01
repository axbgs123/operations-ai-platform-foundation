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
import { GuidedPageHeader } from "@/components/workbench/guided-page-header";
import { useWorkbenchShellContext } from "@/components/workbench/workspace-shell";
import {
  DataTableFrame,
  EmptyState,
  ErrorState,
  Skeleton,
  StatusBadge,
} from "@/components/workbench/ui";
import {
  loadPreflightQueue,
  type PreflightQueuePageData,
} from "@/lib/workbench-api";

const preflightNoEvidence = {
  simple: "暂时没有可用的平台规则资料，这不代表内容安全；请继续人工检查。",
  professional: "NO_ACTIVE_RISK_EVIDENCE：保留确定性结果，不生成虚假 Citation。",
};

export type PreflightFilters = {
  platform?: "douyin" | "xiaohongshu";
  account?: string;
  status?:
    | "pending_scan"
    | "high_risk_blocked"
    | "low_confidence_ocr"
    | "no_active_rag_evidence"
    | "modified_awaiting_rescan"
    | "manually_confirmed"
    | "review_required"
    | "scan_failed";
  sort: "newest" | "oldest";
  page: number;
};

const PLATFORMS = new Set(["douyin", "xiaohongshu"]);
const STATUSES = new Set([
  "pending_scan",
  "high_risk_blocked",
  "low_confidence_ocr",
  "no_active_rag_evidence",
  "modified_awaiting_rescan",
  "manually_confirmed",
  "review_required",
  "scan_failed",
]);
const SORTS = new Set(["newest", "oldest"]);

const statusLabel = {
  pending_scan: "待扫描",
  high_risk_blocked: "高风险阻断",
  low_confidence_ocr: "OCR低置信度",
  no_active_rag_evidence: "无有效RAG证据",
  modified_awaiting_rescan: "已修改待复检",
  manually_confirmed: "已通过人工确认",
  review_required: "待人工确认",
  scan_failed: "检查失败",
} as const;

const nextAction = {
  pending_scan: "执行或等待发布前检查",
  high_risk_blocked: "修改内容后重新检查",
  low_confidence_ocr: "人工核对封面并复检",
  no_active_rag_evidence: "人工复核确定性规则结果",
  modified_awaiting_rescan: "修改后重新检查",
  manually_confirmed: "查看确认记录",
  review_required: "完成人工确认",
  scan_failed: "查看安全错误码并重试",
} as const;

function valid<T extends string>(
  value: string | null,
  allowed: Set<string>,
): T | undefined {
  return value !== null && allowed.has(value) ? value as T : undefined;
}

export function normalizePreflightFilters(
  searchParams: Pick<URLSearchParams, "get">,
  accounts: readonly WorkbenchAccount[],
): PreflightFilters {
  const rawPlatform = searchParams.get("platform");
  const platform = valid<NonNullable<PreflightFilters["platform"]>>(
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
    status: valid<NonNullable<PreflightFilters["status"]>>(
      searchParams.get("status"),
      STATUSES,
    ),
    sort: valid<PreflightFilters["sort"]>(
      searchParams.get("sort"),
      SORTS,
    ) ?? "newest",
    page: Number.isSafeInteger(rawPage) && rawPage > 0 ? rawPage : 1,
  };
}

function updatePreflightFilters(
  current: PreflightFilters,
  change: Partial<PreflightFilters>,
): PreflightFilters {
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

export function preflightFiltersQuery(filters: PreflightFilters): string {
  const query = new URLSearchParams();
  if (filters.platform) query.set("platform", filters.platform);
  if (filters.account) query.set("account", filters.account);
  if (filters.status) query.set("status", filters.status);
  query.set("sort", filters.sort);
  query.set("page", String(filters.page));
  return query.toString();
}

function detailHref(
  workspaceId: string,
  contentId: string,
  filters: PreflightFilters,
): string {
  const returnTo =
    `/workspaces/${workspaceId}/preflight?${preflightFiltersQuery(filters)}`;
  const query = new URLSearchParams({
    tab: "risk",
    returnTo,
  });
  if (filters.platform) query.set("platform", filters.platform);
  if (filters.account) query.set("account", filters.account);
  return `/workspaces/${workspaceId}/contents/${contentId}?${query}`;
}

function tone(
  status: NonNullable<PreflightFilters["status"]>,
): "neutral" | "info" | "success" | "warning" | "danger" {
  if (status === "high_risk_blocked" || status === "scan_failed") {
    return "danger";
  }
  if (
    status === "low_confidence_ocr"
    || status === "no_active_rag_evidence"
    || status === "modified_awaiting_rescan"
    || status === "review_required"
  ) {
    return "warning";
  }
  if (status === "manually_confirmed") return "success";
  if (status === "pending_scan") return "info";
  return "neutral";
}

export function PreflightQueue({
  accounts,
  data,
  filters,
  onFiltersChange,
  workspaceId,
}: {
  accounts: WorkbenchAccount[];
  data: PreflightQueuePageData;
  filters: PreflightFilters;
  onFiltersChange: (filters: PreflightFilters) => void;
  role: "admin" | "editor" | "viewer";
  workspaceId: string;
}): ReactElement {
  const visibleAccounts = accounts.filter(
    (account) => account.platform === filters.platform,
  );
  const change = (changeSet: Partial<PreflightFilters>) => {
    onFiltersChange(updatePreflightFilters(filters, changeSet));
  };

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <GuidedPageHeader
        context={preflightNoEvidence}
        pageId="preflight"
      />
      <section
        aria-label="发布前检查筛选"
        className="grid gap-3 rounded-xl border bg-white p-4 sm:grid-cols-2 lg:grid-cols-4"
      >
        <label className="text-sm font-medium">
          平台
          <select
            aria-label="平台"
            className="mt-1 min-h-10 w-full rounded-lg border bg-white px-3"
            onChange={(event) => change({
              platform: event.target.value
                ? event.target.value as PreflightFilters["platform"]
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
            aria-label="账号"
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
          检查状态
          <select
            aria-label="检查状态"
            className="mt-1 min-h-10 w-full rounded-lg border bg-white px-3"
            onChange={(event) => change({
              status: event.target.value
                ? event.target.value as PreflightFilters["status"]
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
            aria-label="排序"
            className="mt-1 min-h-10 w-full rounded-lg border bg-white px-3"
            onChange={(event) => change({
              sort: event.target.value as PreflightFilters["sort"],
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
          description="请选择抖音或小红书。发布前检查不会跨平台混排。"
          title="请先选择平台"
        />
      ) : !data.items.length ? (
        <EmptyState
          description="调整状态或账号范围后重试。"
          title="当前范围没有发布前事项"
        />
      ) : (
        <>
          <DataTableFrame label="发布前检查桌面列表">
            <table className="hidden min-w-[1120px] w-full text-left text-sm md:table">
              <thead className="bg-slate-50 text-[var(--text-secondary)]">
                <tr>
                  {["内容", "范围", "状态", "OCR", "Evidence", "版本", "下一步"].map(
                    (label) => <th className="px-3 py-3" key={label}>{label}</th>,
                  )}
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr className="border-t" key={item.content_id}>
                    <td className="max-w-72 px-3 py-3">{item.safe_summary}</td>
                    <td className="px-3 py-3">
                      {item.platform === "douyin" ? "抖音" : "小红书"} ·{" "}
                      {item.account_name}
                      <p>{item.column_campaign_name ?? "账号默认"}</p>
                    </td>
                    <td className="px-3 py-3">
                      <StatusBadge tone={tone(item.status)}>
                        {statusLabel[item.status]}
                      </StatusBadge>
                    </td>
                    <td className="px-3 py-3">{item.ocr_status}</td>
                    <td className="px-3 py-3">{item.evidence_status}</td>
                    <td className="px-3 py-3">
                      规则 {item.rule_version ?? "未提供"} · 扫描{" "}
                      {item.scan_version ?? "未提供"}
                    </td>
                    <td className="px-3 py-3">
                      <p>{item.next_action ?? nextAction[item.status]}</p>
                      <Link
                        className="mt-2 inline-flex font-semibold text-[var(--brand)]"
                        href={detailHref(workspaceId, item.content_id, filters)}
                      >
                        查看风险详情
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </DataTableFrame>
          <ul
            aria-label="发布前检查移动卡片"
            className="grid grid-cols-1 gap-3 md:hidden"
          >
            {data.items.map((item) => (
              <li className="rounded-xl border bg-white p-4" key={item.content_id}>
                <div className="flex items-start justify-between gap-3">
                  <p className="font-semibold">{item.safe_summary}</p>
                  <StatusBadge tone={tone(item.status)}>
                    {statusLabel[item.status]}
                  </StatusBadge>
                </div>
                <p className="mt-2 text-sm text-[var(--text-secondary)]">
                  {item.platform === "douyin" ? "抖音" : "小红书"} ·{" "}
                  {item.account_name}
                </p>
                <dl className="mt-3 grid grid-cols-2 gap-3 text-sm">
                  <div><dt>OCR</dt><dd>{item.ocr_status}</dd></div>
                  <div><dt>Evidence</dt><dd>{item.evidence_status}</dd></div>
                  <div><dt>风险</dt><dd>{item.highest_severity ?? "未提供"}</dd></div>
                  <div><dt>下一步</dt><dd>{item.next_action ?? nextAction[item.status]}</dd></div>
                </dl>
                <Link
                  className="mt-4 inline-flex font-semibold text-[var(--brand)]"
                  href={detailHref(workspaceId, item.content_id, filters)}
                >
                  查看风险详情
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}
      {data.pages > 1 ? (
        <nav aria-label="发布前检查分页" className="flex items-center justify-between">
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
  | { status: "ready"; data: PreflightQueuePageData; queryKey: string }
  | { status: "failed"; message: string; queryKey: string };

function emptyData(filters: PreflightFilters): PreflightQueuePageData {
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

export function PreflightQueuePage({
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
  const filters = normalizePreflightFilters(
    new URLSearchParams(searchKey),
    accounts,
  );
  const [state, setState] = useState<QueueState>({ status: "idle" });

  useEffect(() => {
    if (!filters.platform) return;
    const controller = new AbortController();
    loadPreflightQueue(
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
              : "发布前检查队列加载失败",
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

  if (!context) return <Skeleton label="正在加载发布前检查" />;
  if (
    filters.platform
    && (state.status === "idle" || state.queryKey !== searchKey)
  ) {
    return <Skeleton label="正在加载发布前检查队列" />;
  }
  if (state.status === "failed" && state.queryKey === searchKey) {
    return <ErrorState description={state.message} title="发布前检查加载失败" />;
  }
  const data = state.status === "ready" && state.queryKey === searchKey
    ? state.data
    : emptyData(filters);
  return (
    <PreflightQueue
      accounts={accounts}
      data={data}
      filters={filters}
      onFiltersChange={(next) => {
        router.push(`${pathname}?${preflightFiltersQuery(next)}`);
      }}
      role={context.role}
      workspaceId={workspaceId}
    />
  );
}
