"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState, type ReactElement } from "react";

import {
  loadWorkbenchOverview,
  WorkbenchApiError,
  type WorkbenchContext,
  type WorkbenchOverviewData,
} from "@/lib/workbench-api";

import {
  EmptyState,
  ErrorState,
  PageHeader,
  Panel,
  PermissionNotice,
  Skeleton,
  StatusBadge,
} from "./ui";
import { useWorkbenchShellContext } from "./workspace-shell";


type OverviewState =
  | "ready"
  | "loading"
  | "empty"
  | "permission"
  | "error"
  | "dependency_unavailable";

const platformLabel = {
  douyin: "抖音",
  xiaohongshu: "小红书",
} as const;

function percentage(score: number): string {
  return `${Math.round(score * 100)}%`;
}

function scopedAccountHref(
  workspaceId: string,
  account: WorkbenchOverviewData["accounts"][number],
): string {
  const query = new URLSearchParams({
    platform: account.platform,
    account: account.account_id,
  });
  return `/workspaces/${workspaceId}/accounts/${account.account_id}?${query}`;
}

export function WorkbenchOverview({
  workspaceId,
  overview,
  role,
  state = overview?.accounts.length ? "ready" : "empty",
}: {
  workspaceId: string;
  overview?: WorkbenchOverviewData;
  role?: WorkbenchContext["role"];
  state?: OverviewState;
}): ReactElement {
  const shellContext = useWorkbenchShellContext();
  const effectiveRole = role ?? shellContext?.role ?? "viewer";
  if (state === "loading") return <Skeleton label="正在加载工作台" />;
  if (state === "permission") {
    return <PermissionNotice currentRole="当前成员" requiredRole="工作区只读成员" />;
  }
  if (state === "error" || state === "dependency_unavailable") {
    return (
      <ErrorState
        description="工作台只读聚合暂时无法获取，已保存的数据不会受到影响。"
        title={state === "dependency_unavailable" ? "依赖服务暂不可用" : "工作台加载失败"}
      />
    );
  }
  if (state === "empty" || !overview) {
    return (
      <EmptyState
        action={effectiveRole !== "viewer" ? (
          <Link
            className="inline-flex rounded-lg bg-[var(--brand)] px-4 py-2 text-sm font-semibold text-white"
            href={`/workspaces/${workspaceId}/settings`}
          >
            配置平台账号
          </Link>
        ) : undefined}
        description="创建抖音或小红书账号后，这里会分别展示数据状态和运营待办。"
        title="还没有平台账号"
      />
    );
  }

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <PageHeader
        description="按账号分别查看数据完整度、风险和下一步，不混算不同平台的业务指标。"
        title="工作台总览"
      />

      <Panel title="数据状态">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <p className="rounded-lg bg-slate-50 p-4 text-sm">
            <strong className="block text-2xl">
              {overview.data_status.accounts_missing_recommended_snapshot} 个账号缺少推荐快照
            </strong>
          </p>
          <p className="rounded-lg bg-slate-50 p-4 text-sm">
            <strong className="block text-2xl">{overview.data_status.imports_waiting_confirmation}</strong>
            个导入等待确认
          </p>
          <p className="rounded-lg bg-slate-50 p-4 text-sm">
            <strong className="block text-2xl">{overview.data_status.account_count}</strong>
            个平台账号分别核算
          </p>
        </div>
        <ul className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
          {overview.accounts.map((account) => (
            <li className="flex items-center justify-between rounded-lg border p-3" key={account.account_id}>
              <span>{platformLabel[account.platform]} · {account.name}</span>
              <strong>{percentage(account.completeness.score)}</strong>
            </li>
          ))}
        </ul>
      </Panel>

      <Panel title="待处理问题">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <p className="rounded-lg border p-4"><strong>{overview.attention.pending_analysis_count}</strong><span className="ml-2">条待分析内容</span></p>
          <p className="rounded-lg border p-4"><strong>{overview.attention.high_risk_count}</strong><span className="ml-2">条高风险草稿</span></p>
          <p className="rounded-lg border p-4"><strong>{overview.attention.low_confidence_ocr_count}</strong><span className="ml-2">条低置信度 OCR</span></p>
          <p className="rounded-lg border p-4"><strong>{overview.attention.failed_task_count}</strong><span className="ml-2">个失败或待配置任务</span></p>
        </div>
      </Panel>

      <Panel
        description="系统只突出当前最高优先级的一项，不把预计时间作为承诺。"
        title="下一步行动"
      >
        {overview.next_action
        && !(
          effectiveRole === "viewer"
          && overview.next_action.kind === "confirm_import"
        ) ? (
          <Link
            className="inline-flex rounded-lg bg-[var(--brand)] px-4 py-2 text-sm font-semibold text-white"
            href={overview.next_action.href}
          >
            {overview.next_action.label}
          </Link>
        ) : overview.next_action?.kind === "confirm_import"
          && effectiveRole === "viewer" ? (
            <p className="text-sm text-[var(--text-secondary)]">
              该事项需要编辑者或管理员处理
            </p>
        ) : (
          <p className="text-sm text-[var(--text-secondary)]">当前没有必须立即处理的事项。</p>
        )}
      </Panel>

      <Panel title="账号状态">
        <ul aria-label="平台账号状态" className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {overview.accounts.map((account) => (
            <li className="rounded-xl border p-5" key={account.account_id}>
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <StatusBadge tone={account.platform === "douyin" ? "info" : "warning"}>
                    {platformLabel[account.platform]}
                  </StatusBadge>
                  <h3 className="mt-2 text-lg font-semibold">{account.name}</h3>
                </div>
                <StatusBadge tone={account.open_risk_count ? "danger" : "success"}>
                  {account.open_risk_count ? `${account.open_risk_count} 项风险` : "当前无开放风险"}
                </StatusBadge>
              </div>
              <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
                <div><dt className="text-[var(--text-secondary)]">数据完整度</dt><dd className="font-semibold">{percentage(account.completeness.score)}</dd></div>
                <div><dt className="text-[var(--text-secondary)]">待分析</dt><dd className="font-semibold">{account.pending_analysis_count} 条</dd></div>
                <div><dt className="text-[var(--text-secondary)]">快照成熟度</dt><dd className="font-semibold">{account.latest_maturity_bucket ?? "尚无快照"}</dd></div>
                <div><dt className="text-[var(--text-secondary)]">本周闭环</dt><dd className="font-semibold">{account.has_current_week_closed_loop ? "已确认闭环" : "尚未确认闭环"}</dd></div>
              </dl>
              <Link
                aria-label={`查看${account.name}`}
                className="mt-5 inline-flex text-sm font-semibold text-[var(--brand)]"
                href={scopedAccountHref(workspaceId, account)}
              >
                查看账号 →
              </Link>
            </li>
          ))}
        </ul>
      </Panel>

      <Panel title="快捷操作">
        <nav aria-label="工作台快捷操作" className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            ["新建内容", `/workspaces/${workspaceId}/contents/new`],
            ["导入数据", `/workspaces/${workspaceId}/imports`],
            ["分析中心", `/workspaces/${workspaceId}/analysis`],
            ["生成中心", `/workspaces/${workspaceId}/generation`],
          ].filter(([label]) => (
            effectiveRole !== "viewer" || label === "分析中心"
          )).map(([label, href]) => (
            <Link className="rounded-lg border px-4 py-3 text-center text-sm font-semibold hover:border-[var(--brand)]" href={href} key={href}>
              {label}
            </Link>
          ))}
        </nav>
      </Panel>
    </div>
  );
}

export function WorkbenchOverviewPage({
  workspaceId,
}: {
  workspaceId: string;
}): ReactElement {
  const searchParams = useSearchParams();
  const rawPlatform = searchParams.get("platform");
  const platform = rawPlatform === "douyin" || rawPlatform === "xiaohongshu"
    ? rawPlatform
    : undefined;
  const accountId = platform ? searchParams.get("account") ?? undefined : undefined;
  const [state, setState] = useState<{
    kind: OverviewState;
    overview?: WorkbenchOverviewData;
  }>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    loadWorkbenchOverview(
      workspaceId,
      controller.signal,
      {
        ...(platform ? { platform } : {}),
        ...(accountId ? { account_id: accountId } : {}),
      },
    )
      .then((overview) => setState({
        kind: overview.accounts.length ? "ready" : "empty",
        overview,
      }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState({
          kind: error instanceof WorkbenchApiError && error.status === 403
            ? "permission"
            : "dependency_unavailable",
        });
      });
    return () => controller.abort();
  }, [accountId, platform, workspaceId]);

  return (
    <WorkbenchOverview
      overview={state.overview}
      state={state.kind}
      workspaceId={workspaceId}
    />
  );
}
