"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import {
  AccountDashboardData,
  dashboardDrillDownHref,
  loadAccountDashboard,
} from "@/lib/dashboard-api";

import { ChartPanel } from "./chart-panel";


const formatNumber = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 });

export function AccountDashboard({
  workspaceId,
  accountId,
  initialContentType = "image_text",
  initialMaturityBucket = "24h",
}: {
  workspaceId: string;
  accountId: string;
  initialContentType?: "video" | "image_text";
  initialMaturityBucket?: "1h" | "24h" | "72h" | "7d";
}) {
  const [dashboard, setDashboard] = useState<AccountDashboardData | null>(null);
  const [error, setError] = useState("");
  const [contentType, setContentType] = useState(initialContentType);
  const [maturityBucket, setMaturityBucket] = useState(initialMaturityBucket);

  useEffect(() => {
    let active = true;
    loadAccountDashboard(workspaceId, accountId, contentType, maturityBucket)
      .then((data) => { if (active) setDashboard(data); })
      .catch((caught: unknown) => {
        if (active) setError(caught instanceof Error ? caught.message : "仪表盘加载失败");
      });
    return () => { active = false; };
  }, [accountId, contentType, maturityBucket, workspaceId]);

  function updateScope(
    nextContentType: "video" | "image_text",
    nextMaturityBucket: "1h" | "24h" | "72h" | "7d",
  ) {
    setError("");
    setContentType(nextContentType);
    setMaturityBucket(nextMaturityBucket);
    const query = new URLSearchParams(window.location.search);
    query.set("content_type", nextContentType);
    query.set("maturity_bucket", nextMaturityBucket);
    window.history.replaceState(null, "", `?${query}`);
  }

  if (error) return <p className="rounded-2xl bg-rose-950/60 p-5 text-rose-200">{error}</p>;
  if (!dashboard) return <p className="text-slate-400">正在加载账号证据…</p>;

  return (
    <section className="space-y-8">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-sm font-medium text-cyan-300">账号状态 · {dashboard.platform}</p>
          <h1 className="mt-2 text-3xl font-semibold sm:text-4xl">{dashboard.account_name}</h1>
          <p className="mt-3 text-slate-300">实际样本 {dashboard.sample_count} 条</p>
          <p className="mt-1 max-w-3xl text-sm text-slate-400">{dashboard.explanation}</p>
        </div>
        <div className="grid w-full grid-cols-2 gap-3 text-sm sm:w-auto">
          <label className="text-slate-400">
            内容类型
            <select
              className="mt-1 block w-full rounded-xl bg-slate-800 px-3 py-2 text-slate-100"
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
          <label className="text-slate-400">
            成熟度
            <select
              className="mt-1 block w-full rounded-xl bg-slate-800 px-3 py-2 text-slate-100"
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
      </header>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {dashboard.goal_cards.map((card) => (
          <Link
            className="rounded-3xl border border-slate-800 bg-slate-900 p-5 hover:border-cyan-500"
            href={dashboardDrillDownHref(card.drill_down_filter)}
            key={card.metric_key}
          >
            <p className="text-sm text-slate-400">{card.label}</p>
            <p className="mt-2 text-3xl font-semibold">
              {card.current_value === null ? "—" : formatNumber.format(card.current_value)}
            </p>
            <div className="mt-4 flex flex-wrap gap-3 text-xs text-slate-400">
              <span>较上一条内容 {card.change_rate === null ? "—" : `${formatNumber.format(card.change_rate * 100)}%`}</span>
              <span>历史分位 {card.historical_percentile === null ? "—" : `${formatNumber.format(card.historical_percentile * 100)}%`}</span>
              <span>完整度 {formatNumber.format(card.data_completeness * 100)}%</span>
            </div>
            <p className="mt-3 text-xs text-slate-500">
              有效样本 {card.sample_count} 条 · {card.explanation}
            </p>
          </Link>
        ))}
      </div>

      {dashboard.charts.length ? (
        <section>
          <h2 className="text-2xl font-semibold">数据趋势</h2>
          <div className="mt-4 grid gap-5 xl:grid-cols-2">
            {dashboard.charts.map((chart) => <ChartPanel chart={chart} key={chart.id} />)}
          </div>
        </section>
      ) : null}

      <div className="grid gap-5 lg:grid-cols-2">
        <section className="rounded-3xl border border-slate-800 bg-slate-900 p-6">
          <h2 className="text-2xl font-semibold">值得关注</h2>
          {dashboard.attention_items.length ? (
            <ul className="mt-4 space-y-3">
              {dashboard.attention_items.map((item) => (
                <li key={`${item.kind}:${item.content_id}`}>
                  <Link className="block rounded-2xl bg-slate-950 p-4 hover:ring-1 hover:ring-cyan-500" href={dashboardDrillDownHref(item.drill_down_filter)}>
                    <span className={item.kind === "candidate" ? "text-emerald-300" : "text-amber-300"}>
                      {item.kind === "candidate" ? "候选" : "异常"}
                    </span>
                    <p className="mt-1 font-medium">{item.title}</p>
                    <p className="mt-1 text-sm text-slate-400">{item.reason}</p>
                  </Link>
                </li>
              ))}
            </ul>
          ) : <p className="mt-4 text-sm text-slate-400">当前样本不足以判断候选或异常。</p>}
        </section>

        <section className="rounded-3xl border border-slate-800 bg-slate-900 p-6">
          <h2 className="text-2xl font-semibold">下一步行动</h2>
          <ol className="mt-4 space-y-3 text-slate-300">
            {dashboard.next_actions.map((action, index) => (
              <li className="flex gap-3" key={action}>
                <span className="text-cyan-300">{index + 1}.</span><span>{action}</span>
              </li>
            ))}
          </ol>
        </section>
      </div>
    </section>
  );
}
