"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState, type ReactElement } from "react";

import {
  loadWorkbenchOverview,
  type WorkbenchOverviewData,
} from "@/lib/workbench-api";

import {
  EmptyState,
  ErrorState,
  PageHeader,
  Skeleton,
  StatusBadge,
} from "@/components/workbench/ui";


const platformLabel = {
  douyin: "抖音",
  xiaohongshu: "小红书",
} as const;

type AccountCard = WorkbenchOverviewData["accounts"][number];

export function filterAccountsByScope(
  accounts: WorkbenchOverviewData["accounts"],
  platform: string | null,
  accountId: string | null,
): WorkbenchOverviewData["accounts"] {
  if (platform !== null && platform !== "douyin" && platform !== "xiaohongshu") {
    return [];
  }
  return accounts.filter((account) =>
    (platform === null || account.platform === platform)
    && (accountId === null || account.account_id === accountId)
  );
}

function scopedHref(
  workspaceId: string,
  account: AccountCard,
): string {
  const query = new URLSearchParams({
    platform: account.platform,
    account: account.account_id,
  });
  return `/workspaces/${workspaceId}/accounts/${account.account_id}?${query}`;
}

function contentTypeLabel(
  account: AccountCard,
): string {
  const labels: string[] = [];
  if (account.content_type_counts.video) {
    labels.push(`视频 ${account.content_type_counts.video} 条`);
  }
  if (account.content_type_counts.image_text) {
    labels.push(`图文 ${account.content_type_counts.image_text} 条`);
  }
  return labels.join(" · ") || "尚无内容";
}

export function AccountList({
  accounts,
  workspaceId,
}: {
  accounts: WorkbenchOverviewData["accounts"];
  workspaceId: string;
}): ReactElement {
  if (!accounts.length) {
    return (
      <EmptyState
        description="创建账号后可分别查看平台指标、样本门禁和运营行动。"
        title="还没有账号"
      />
    );
  }
  return (
    <ul
      aria-label="账号仪表盘列表"
      className="grid grid-cols-1 gap-4 lg:grid-cols-2"
    >
      {accounts.map((account) => (
        <li className="rounded-xl border bg-white p-5" key={account.account_id}>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <StatusBadge tone={account.platform === "douyin" ? "info" : "warning"}>
                {platformLabel[account.platform]}
              </StatusBadge>
              <h2 className="mt-2 text-lg font-semibold">{account.name}</h2>
              <p className="mt-1 text-sm text-[var(--text-secondary)]">
                {contentTypeLabel(account)}
              </p>
            </div>
            <StatusBadge tone={account.open_risk_count ? "danger" : "success"}>
              {account.open_risk_count ? `${account.open_risk_count} 项开放风险` : "当前无开放风险"}
            </StatusBadge>
          </div>
          <dl className="mt-5 grid grid-cols-1 gap-3 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-[var(--text-secondary)]">数据完整度</dt>
              <dd className="font-semibold">{Math.round(account.completeness.score * 100)}%</dd>
            </div>
            <div>
              <dt className="text-[var(--text-secondary)]">快照成熟度</dt>
              <dd className="font-semibold">
                {account.latest_maturity_bucket
                  ? `${account.latest_maturity_bucket} · ${account.confirmed_snapshot_count} 条已确认快照`
                  : "尚无已确认快照"}
              </dd>
            </div>
            <div>
              <dt className="text-[var(--text-secondary)]">待分析数量</dt>
              <dd className="font-semibold">{account.pending_analysis_count} 条</dd>
            </div>
            <div>
              <dt className="text-[var(--text-secondary)]">风险状态</dt>
              <dd className="font-semibold">
                {account.open_risk_count ? `${account.open_risk_count} 项开放风险` : "当前正常"}
              </dd>
            </div>
          </dl>
          <Link
            aria-label={`查看${account.name}`}
            className="mt-5 inline-flex rounded-lg bg-[var(--brand)] px-4 py-2 text-sm font-semibold text-white"
            href={scopedHref(workspaceId, account)}
          >
            查看账号
          </Link>
        </li>
      ))}
    </ul>
  );
}

export function AccountListPage({
  workspaceId,
}: {
  workspaceId: string;
}): ReactElement {
  const searchParams = useSearchParams();
  const [state, setState] = useState<
    | { status: "loading" }
    | { status: "ready"; data: WorkbenchOverviewData }
    | { status: "failed" }
  >({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    loadWorkbenchOverview(workspaceId, controller.signal)
      .then((data) => setState({ status: "ready", data }))
      .catch(() => {
        if (!controller.signal.aborted) setState({ status: "failed" });
      });
    return () => controller.abort();
  }, [workspaceId]);

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <PageHeader
        description="抖音与小红书账号分别展示，不进行跨平台指标合计。"
        title="账号仪表盘"
      />
      {state.status === "loading" ? <Skeleton label="正在加载账号列表" /> : null}
      {state.status === "failed" ? (
        <ErrorState
          description="无法加载账号只读状态，请检查连接后重试。"
          title="账号列表加载失败"
        />
      ) : null}
      {state.status === "ready" ? (
        <AccountList
          accounts={filterAccountsByScope(
            state.data.accounts,
            searchParams.get("platform"),
            searchParams.get("account"),
          )}
          workspaceId={workspaceId}
        />
      ) : null}
    </div>
  );
}
