"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  FormEvent,
  useEffect,
  useMemo,
  useState,
  type ReactElement,
} from "react";

import { loadColumnCampaigns } from "@/lib/account-api";
import {
  loadWorkspaceContents,
  type ContentListPageData,
  type ContentListQuery,
} from "@/lib/content-api";
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


export type ContentColumnOption = {
  id: string;
  account_id: string;
  platform: "douyin" | "xiaohongshu";
  name: string;
};

export type ContentFilters = ContentListQuery;

const PLATFORM_VALUES = new Set(["douyin", "xiaohongshu"]);
const CONTENT_TYPE_VALUES = new Set(["video", "image_text"]);
const STATUS_VALUES = new Set(["draft", "published", "archived"]);
const MATURITY_VALUES = new Set(["1h", "24h", "72h", "7d"]);
const SORT_VALUES = new Set([
  "newest",
  "oldest",
  "title_asc",
  "title_desc",
  "published_desc",
]);

function validValue<T extends string>(
  value: string | null,
  values: Set<string>,
): T | undefined {
  return value !== null && values.has(value) ? value as T : undefined;
}

export function normalizeContentFilters(
  searchParams: Pick<URLSearchParams, "get" | "getAll">,
  accounts: readonly WorkbenchAccount[],
  columns: readonly ContentColumnOption[],
): ContentFilters {
  const rawPlatform = searchParams.get("platform");
  if (rawPlatform !== null && !PLATFORM_VALUES.has(rawPlatform)) {
    return {
      sort: validValue<ContentFilters["sort"]>(
        searchParams.get("sort"),
        SORT_VALUES,
      ) ?? "newest",
      page: 1,
    };
  }
  const platform = validValue<ContentFilters["platform"] & string>(
    rawPlatform,
    PLATFORM_VALUES,
  );
  const rawAccount = searchParams.get("account");
  const accountItem = accounts.find((item) => item.account_id === rawAccount);
  const account = accountItem && (!platform || accountItem.platform === platform)
    ? accountItem.account_id
    : undefined;
  const resolvedPlatform = platform ?? accountItem?.platform;
  const rawColumn = searchParams.get("column");
  const columnItem = columns.find((item) => item.id === rawColumn);
  const column = columnItem
    && (!account || columnItem.account_id === account)
    && (!resolvedPlatform || columnItem.platform === resolvedPlatform)
    ? columnItem.id
    : undefined;
  const rawPage = Number(searchParams.get("page") ?? "1");
  return {
    platform: resolvedPlatform,
    account,
    column,
    contentType: validValue<NonNullable<ContentFilters["contentType"]>>(
      searchParams.get("contentType"),
      CONTENT_TYPE_VALUES,
    ),
    status: validValue<NonNullable<ContentFilters["status"]>>(
      searchParams.get("status"),
      STATUS_VALUES,
    ),
    maturity: validValue<NonNullable<ContentFilters["maturity"]>>(
      searchParams.get("maturity"),
      MATURITY_VALUES,
    ),
    query: searchParams.get("query")?.trim().slice(0, 300) || undefined,
    metricKey: searchParams.get("metric_key")?.trim().slice(0, 80) || undefined,
    requiredMetricKeys: searchParams.getAll("required_metric_keys")
      .map((value) => value.trim().slice(0, 80))
      .filter(Boolean)
      .slice(0, 20),
    attention: validValue<NonNullable<ContentFilters["attention"]>>(
      searchParams.get("attention"),
      new Set(["candidate", "anomaly"]),
    ),
    sort: validValue<ContentFilters["sort"]>(
      searchParams.get("sort"),
      SORT_VALUES,
    ) ?? "newest",
    page: Number.isSafeInteger(rawPage) && rawPage > 0 ? rawPage : 1,
  };
}

export function updateContentFilters(
  current: ContentFilters,
  change: Partial<ContentFilters>,
): ContentFilters {
  const next = { ...current, ...change, page: 1 };
  if (
    Object.hasOwn(change, "platform")
    && change.platform !== current.platform
  ) {
    next.account = undefined;
    next.column = undefined;
  }
  if (
    Object.hasOwn(change, "account")
    && change.account !== current.account
  ) {
    next.column = undefined;
  }
  if (Object.hasOwn(change, "page")) {
    next.page = change.page ?? 1;
  }
  return next;
}

export function contentFiltersQuery(filters: ContentFilters): string {
  const query = new URLSearchParams();
  if (filters.platform) query.set("platform", filters.platform);
  if (filters.account) query.set("account", filters.account);
  if (filters.column) query.set("column", filters.column);
  if (filters.contentType) query.set("contentType", filters.contentType);
  if (filters.status) query.set("status", filters.status);
  if (filters.maturity) query.set("maturity", filters.maturity);
  if (filters.query) query.set("query", filters.query);
  if (filters.metricKey) query.set("metric_key", filters.metricKey);
  for (const key of filters.requiredMetricKeys ?? []) {
    query.append("required_metric_keys", key);
  }
  if (filters.attention) query.set("attention", filters.attention);
  query.set("sort", filters.sort);
  query.set("page", String(filters.page));
  return query.toString();
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

const analysisLabel = {
  not_requested: "待分析",
  pending: "排队中",
  running: "分析中",
  succeeded: "已分析",
  failed: "分析失败",
} as const;

const riskLabel = {
  not_scanned: "未扫描",
  pending: "扫描中",
  clear: "当前未见命中",
  low: "低风险",
  medium: "中风险",
  high: "高风险",
  failed: "扫描失败",
} as const;

function riskTone(
  risk: keyof typeof riskLabel,
): "neutral" | "info" | "success" | "warning" | "danger" {
  if (risk === "high" || risk === "failed") return "danger";
  if (risk === "medium" || risk === "low") return "warning";
  if (risk === "clear") return "success";
  if (risk === "pending") return "info";
  return "neutral";
}

function detailHref(
  workspaceId: string,
  contentId: string,
  filters: ContentFilters,
): string {
  const returnTo = (
    `/workspaces/${workspaceId}/contents?${contentFiltersQuery(filters)}`
  );
  const query = new URLSearchParams({ returnTo });
  if (filters.platform) query.set("platform", filters.platform);
  if (filters.account) query.set("account", filters.account);
  return `/workspaces/${workspaceId}/contents/${contentId}?${query}`;
}

function FilterSelect({
  label,
  value,
  onChange,
  children,
}: {
  label: string;
  value?: string;
  onChange: (value: string | undefined) => void;
  children: React.ReactNode;
}): ReactElement {
  return (
    <label className="text-sm font-medium">
      {label}
      <select
        className="mt-1 min-h-10 w-full rounded-lg border bg-white px-3"
        onChange={(event) => onChange(event.target.value || undefined)}
        value={value ?? ""}
      >
        <option value="">全部</option>
        {children}
      </select>
    </label>
  );
}

export function ContentList({
  accounts,
  columns,
  data,
  filters,
  onFiltersChange,
  role,
  workspaceId,
}: {
  accounts: WorkbenchAccount[];
  columns: ContentColumnOption[];
  data: ContentListPageData;
  filters: ContentFilters;
  onFiltersChange: (filters: ContentFilters) => void;
  role: "admin" | "editor" | "viewer";
  workspaceId: string;
}): ReactElement {
  const [searchDraft, setSearchDraft] = useState(filters.query ?? "");
  useEffect(() => setSearchDraft(filters.query ?? ""), [filters.query]);
  const visibleAccounts = accounts.filter(
    (account) => !filters.platform || account.platform === filters.platform,
  );
  const visibleColumns = columns.filter(
    (column) =>
      (!filters.platform || column.platform === filters.platform)
      && (!filters.account || column.account_id === filters.account),
  );

  function change(change: Partial<ContentFilters>) {
    onFiltersChange(updateContentFilters(filters, change));
  }

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    change({ query: searchDraft.trim().slice(0, 300) || undefined });
  }

  const primaryAction = role === "viewer"
    ? undefined
    : (
        <Link
          className="rounded-lg bg-[var(--brand)] px-4 py-2 text-sm font-semibold text-white"
          href={`/workspaces/${workspaceId}/contents/new`}
        >
          新建内容
        </Link>
      );

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <PageHeader
        description="按平台、账号、栏目和数据状态查找内容；平台数据始终分别展示。"
        primaryAction={primaryAction}
        secondaryActions={role === "viewer" ? undefined : (
          <Link
            className="rounded-lg border bg-white px-4 py-2 text-sm font-semibold"
            href={`/workspaces/${workspaceId}/imports`}
          >
            导入数据
          </Link>
        )}
        title="内容库"
      />
      <section
        aria-label="内容筛选"
        className="grid gap-3 rounded-xl border bg-white p-4 sm:grid-cols-2 xl:grid-cols-4"
      >
        <FilterSelect
          label="平台"
          onChange={(platform) => change({
            platform: platform as ContentFilters["platform"],
          })}
          value={filters.platform}
        >
          <option value="douyin">抖音</option>
          <option value="xiaohongshu">小红书</option>
        </FilterSelect>
        <FilterSelect
          label="账号"
          onChange={(account) => change({ account })}
          value={filters.account}
        >
          {visibleAccounts.map((account) => (
            <option key={account.account_id} value={account.account_id}>
              {account.name}
            </option>
          ))}
        </FilterSelect>
        <FilterSelect
          label="栏目/活动"
          onChange={(column) => change({ column })}
          value={filters.column}
        >
          {visibleColumns.map((column) => (
            <option key={column.id} value={column.id}>{column.name}</option>
          ))}
        </FilterSelect>
        <FilterSelect
          label="内容类型"
          onChange={(contentType) => change({
            contentType: contentType as ContentFilters["contentType"],
          })}
          value={filters.contentType}
        >
          <option value="video">视频</option>
          <option value="image_text">图文</option>
        </FilterSelect>
        <FilterSelect
          label="生命周期"
          onChange={(status) => change({
            status: status as ContentFilters["status"],
          })}
          value={filters.status}
        >
          <option value="draft">灵感/选题</option>
          <option value="published">已发布</option>
          <option value="archived">历史归档</option>
        </FilterSelect>
        <FilterSelect
          label="成熟度"
          onChange={(maturity) => change({
            maturity: maturity as ContentFilters["maturity"],
          })}
          value={filters.maturity}
        >
          <option value="1h">1h</option>
          <option value="24h">24h</option>
          <option value="72h">72h</option>
          <option value="7d">7d</option>
        </FilterSelect>
        <form className="text-sm font-medium" onSubmit={submitSearch}>
          <label htmlFor="content-title-search">标题搜索</label>
          <div className="mt-1 flex">
            <input
              className="min-h-10 min-w-0 flex-1 rounded-l-lg border px-3"
              id="content-title-search"
              maxLength={300}
              onChange={(event) => setSearchDraft(event.target.value)}
              value={searchDraft}
            />
            <button
              className="rounded-r-lg border border-l-0 bg-slate-50 px-3"
              type="submit"
            >
              搜索
            </button>
          </div>
        </form>
        <FilterSelect
          label="排序"
          onChange={(sort) => change({
            sort: (sort ?? "newest") as ContentFilters["sort"],
          })}
          value={filters.sort}
        >
          <option value="newest">最新创建</option>
          <option value="oldest">最早创建</option>
          <option value="published_desc">最近发布</option>
          <option value="title_asc">标题 A–Z</option>
          <option value="title_desc">标题 Z–A</option>
        </FilterSelect>
      </section>
      {filters.metricKey || filters.requiredMetricKeys?.length || filters.attention ? (
        <p className="rounded-lg bg-blue-50 px-4 py-3 text-sm" role="status">
          当前为账号图表下钻范围：
          {filters.metricKey ? `指标 ${filters.metricKey}` : "组合指标"}
          {filters.attention ? ` · ${filters.attention === "candidate" ? "候选" : "异常"}` : ""}
          。筛选由现有动态基准服务执行。
        </p>
      ) : null}

      {!data.items.length ? (
        <EmptyState
          description="调整筛选条件，或创建第一条内容。"
          title="没有符合条件的内容"
        />
      ) : (
        <>
          <DataTableFrame label="内容库桌面列表">
            <table
              aria-label="内容库桌面列表"
              className="hidden min-w-[1320px] w-full text-left text-sm md:table"
            >
              <thead className="bg-slate-50 text-[var(--text-secondary)]">
                <tr>
                  {[
                    "封面",
                    "标题",
                    "平台/账号",
                    "栏目/活动",
                    "类型",
                    "生命周期",
                    "发布时间",
                    "成熟度",
                    "完整度",
                    "分析",
                    "风控",
                    "下一步",
                  ].map((label) => (
                    <th className="px-3 py-3 font-semibold" key={label}>
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr className="border-t" key={item.id}>
                    <td className="px-3 py-3">
                      {item.cover?.download_url ? (
                        <span
                          aria-label={`${item.title}封面`}
                          className="block h-12 w-16 rounded bg-cover bg-center"
                          role="img"
                          style={{
                            backgroundImage: `url(${item.cover.download_url})`,
                          }}
                        />
                      ) : <span className="text-xs text-slate-500">暂无</span>}
                    </td>
                    <td className="max-w-56 px-3 py-3 font-medium">{item.title}</td>
                    <td className="px-3 py-3">
                      {platformLabel[item.platform]} · {item.account_name}
                    </td>
                    <td className="px-3 py-3">
                      {item.column_campaign_name ?? "账号默认"}
                    </td>
                    <td className="px-3 py-3">
                      {item.content_type === "video" ? "视频" : "图文"}
                    </td>
                    <td className="px-3 py-3">
                      {lifecycleLabel[item.lifecycle_status]}
                    </td>
                    <td className="px-3 py-3">
                      {item.published_at
                        ? new Date(item.published_at).toLocaleString("zh-CN")
                        : "未发布"}
                    </td>
                    <td className="px-3 py-3">
                      {item.latest_maturity ?? "暂无快照"}
                    </td>
                    <td className="px-3 py-3">
                      {Math.round(item.data_completeness * 100)}%
                    </td>
                    <td className="px-3 py-3">
                      {analysisLabel[item.analysis_status]}
                    </td>
                    <td className="px-3 py-3">
                      <StatusBadge tone={riskTone(item.risk_status)}>
                        {riskLabel[item.risk_status]}
                      </StatusBadge>
                    </td>
                    <td className="px-3 py-3">
                      <Link
                        className="font-semibold text-[var(--brand)]"
                        href={detailHref(workspaceId, item.id, filters)}
                      >
                        查看内容
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </DataTableFrame>
          <ul
            aria-label="内容库移动卡片"
            className="grid grid-cols-1 gap-3 md:hidden"
          >
            {data.items.map((item) => (
              <li className="rounded-xl border bg-white p-4" key={item.id}>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-semibold">{item.title}</p>
                    <p className="mt-1 text-sm text-[var(--text-secondary)]">
                      {platformLabel[item.platform]} · {item.account_name}
                    </p>
                  </div>
                  <StatusBadge tone={riskTone(item.risk_status)}>
                    {riskLabel[item.risk_status]}
                  </StatusBadge>
                </div>
                <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
                  <div><dt>生命周期</dt><dd>{lifecycleLabel[item.lifecycle_status]}</dd></div>
                  <div><dt>成熟度</dt><dd>{item.latest_maturity ?? "暂无快照"}</dd></div>
                  <div><dt>分析</dt><dd>{analysisLabel[item.analysis_status]}</dd></div>
                  <div><dt>风控</dt><dd>{riskLabel[item.risk_status]}</dd></div>
                </dl>
                <Link
                  className="mt-4 inline-flex font-semibold text-[var(--brand)]"
                  href={detailHref(workspaceId, item.id, filters)}
                >
                  查看内容
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}
      {data.pages > 1 ? (
        <nav aria-label="内容分页" className="flex items-center justify-between">
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

type PageState =
  | { status: "loading" }
  | {
      status: "ready";
      data: ContentListPageData;
      columns: ContentColumnOption[];
      queryKey: string;
    }
  | { status: "failed"; message: string };

export function ContentLibraryPage({
  workspaceId,
}: {
  workspaceId: string;
}): ReactElement {
  const context = useWorkbenchShellContext();
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const accounts = useMemo(() => context?.accounts ?? [], [context?.accounts]);
  const [state, setState] = useState<PageState>({ status: "loading" });
  const searchKey = searchParams.toString();

  useEffect(() => {
    const controller = new AbortController();
    Promise.all(
      accounts.map(async (account) => {
        const items = await loadColumnCampaigns(workspaceId, account.account_id);
        return items.map((item) => ({
          id: item.id,
          account_id: account.account_id,
          platform: account.platform,
          name: item.name,
        }));
      }),
    )
      .then((groups) => {
        const columns = groups.flat();
        const filters = normalizeContentFilters(
          new URLSearchParams(searchKey),
          accounts,
          columns,
        );
        return loadWorkspaceContents(workspaceId, filters, controller.signal)
          .then((data) => setState({
            status: "ready",
            data,
            columns,
            queryKey: searchKey,
          }));
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) {
          setState({
            status: "failed",
            message: caught instanceof Error ? caught.message : "内容库加载失败",
          });
        }
      });
    return () => controller.abort();
  }, [accounts, searchKey, workspaceId]);

  if (
    !context
    || state.status === "loading"
    || (state.status === "ready" && state.queryKey !== searchKey)
  ) {
    return <Skeleton label="正在加载内容库" />;
  }
  if (state.status === "failed") {
    return (
      <ErrorState
        description={state.message}
        title="内容库加载失败"
      />
    );
  }
  const filters = normalizeContentFilters(
    new URLSearchParams(searchKey),
    accounts,
    state.columns,
  );
  return (
    <ContentList
      accounts={accounts}
      columns={state.columns}
      data={state.data}
      filters={filters}
      onFiltersChange={(next) => {
        router.push(`${pathname}?${contentFiltersQuery(next)}`);
      }}
      role={context.role}
      workspaceId={workspaceId}
    />
  );
}
