"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import {
  DashboardContentItem,
  DashboardFilter,
  loadDashboardContents,
} from "@/lib/dashboard-api";


export function DrillDownContentList({
  workspaceId,
  filters,
}: {
  workspaceId: string;
  filters: Partial<DashboardFilter>;
}) {
  const [contents, setContents] = useState<DashboardContentItem[]>([]);
  const [error, setError] = useState("");
  const {
    account_id: accountId,
    platform,
    content_type: contentType,
    maturity_bucket: maturityBucket,
    metric_key: metricKey,
    required_metric_keys: requiredMetricKeys,
    attention,
  } = filters;
  const hasCompleteFilter = Boolean(
    accountId && platform && contentType && maturityBucket,
  );

  useEffect(() => {
    let active = true;
    if (!accountId || !platform || !contentType || !maturityBucket) return;
    loadDashboardContents({
      workspace_id: workspaceId,
      account_id: accountId,
      platform,
      content_type: contentType,
      maturity_bucket: maturityBucket,
      metric_key: metricKey,
      required_metric_keys: requiredMetricKeys,
      attention,
    })
      .then((items) => {
        if (active) setContents(items);
      })
      .catch((caught: unknown) => {
        if (active) setError(caught instanceof Error ? caught.message : "内容加载失败");
      });
    return () => { active = false; };
  }, [
    accountId,
    attention,
    contentType,
    maturityBucket,
    metricKey,
    platform,
    requiredMetricKeys,
    workspaceId,
  ]);

  if (!hasCompleteFilter) return <p className="text-rose-200">下钻筛选条件不完整</p>;
  if (error) return <p className="rounded-xl bg-rose-950/60 p-4 text-rose-200">{error}</p>;
  return (
    <section className="space-y-5">
      <header>
        <p className="text-sm font-medium text-cyan-300">图表下钻</p>
        <h1 className="mt-2 text-3xl font-semibold">对应内容列表</h1>
        <p className="mt-3 text-sm text-slate-400">
          {filters.platform ?? "全部平台"} · {filters.content_type ?? "全部类型"} · {filters.maturity_bucket ?? "全部成熟度"}
          {filters.metric_key ? ` · 指标 ${filters.metric_key}` : ""}
          {filters.attention ? ` · ${filters.attention}` : ""}
        </p>
      </header>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {contents.map((content) => (
          <Link
            className="rounded-2xl border border-slate-800 bg-slate-900 p-5 hover:border-cyan-500"
            href={`/workspaces/${workspaceId}/contents/${content.content_id}`}
            key={content.content_id}
          >
            <p className="font-medium">{content.title}</p>
            <p className="mt-2 text-sm text-slate-400">{content.account_name} · {content.status}</p>
          </Link>
        ))}
      </div>
      {!contents.length ? <p className="text-slate-400">没有符合当前筛选条件的内容。</p> : null}
    </section>
  );
}
