"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import {
  analyzeCommentDemands,
  collectCompetitorAccount,
  createCompetitorAccount,
  getCommentDemands,
  getCompetitorAccounts,
  getPublicOperationsReport,
  getPublicTrendSearches,
  searchPublicTrends,
  type CommentDemand,
  type CompetitorAccount,
  type PublicOperationsReport,
  type PublicTrendSearch,
} from "@/lib/public-data-api";
import { EmptyState, ErrorState, Panel, Skeleton, StatusBadge } from "@/components/workbench/ui";
import { useWorkbenchShellContext } from "@/components/workbench/workspace-shell";

type Platform = "douyin" | "xiaohongshu";

const control = "mt-1.5 w-full rounded-xl border border-[var(--border)] bg-white px-3 py-2.5 text-[var(--text-primary)]";
const primaryButton = "rounded-lg bg-[var(--brand)] px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50";
const secondaryButton = "rounded-lg border border-[var(--border)] bg-white px-3 py-2 text-sm font-semibold disabled:opacity-50";
const csrf = () => sessionStorage.getItem("workspace_csrf") ?? "";
const platformName = (platform: Platform) => platform === "douyin" ? "抖音" : "小红书";

function formatCount(value: number | null | undefined) {
  if (value === null || value === undefined) return "未提供";
  return new Intl.NumberFormat("zh-CN", { notation: value >= 10_000 ? "compact" : "standard" }).format(value);
}

export function PublicIntelligenceCenter({ workspaceId }: { workspaceId: string }) {
  const context = useWorkbenchShellContext();
  const [competitors, setCompetitors] = useState<CompetitorAccount[]>([]);
  const [analyses, setAnalyses] = useState<CommentDemand[]>([]);
  const [report, setReport] = useState<PublicOperationsReport>();
  const [searches, setSearches] = useState<PublicTrendSearch[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [competitorPlatform, setCompetitorPlatform] = useState<Platform>("douyin");
  const [competitorName, setCompetitorName] = useState("");
  const [competitorUrl, setCompetitorUrl] = useState("");
  const [competitorId, setCompetitorId] = useState("");
  const [commentPlatform, setCommentPlatform] = useState<Platform>("douyin");
  const [commentUrl, setCommentUrl] = useState("");
  const [commentId, setCommentId] = useState("");
  const [searchPlatform, setSearchPlatform] = useState<Platform>("douyin");
  const [searchKeyword, setSearchKeyword] = useState("");

  const refresh = useCallback(async () => {
    const [nextCompetitors, nextAnalyses, nextReport, nextSearches] = await Promise.all([
      getCompetitorAccounts(workspaceId),
      getCommentDemands(workspaceId),
      getPublicOperationsReport(workspaceId),
      getPublicTrendSearches(workspaceId),
    ]);
    setCompetitors(nextCompetitors);
    setAnalyses(nextAnalyses);
    setReport(nextReport);
    setSearches(nextSearches);
  }, [workspaceId]);

  useEffect(() => {
    let active = true;
    Promise.all([
      getCompetitorAccounts(workspaceId),
      getCommentDemands(workspaceId),
      getPublicOperationsReport(workspaceId),
      getPublicTrendSearches(workspaceId),
    ])
      .then(([nextCompetitors, nextAnalyses, nextReport, nextSearches]) => {
        if (!active) return;
        setCompetitors(nextCompetitors);
        setAnalyses(nextAnalyses);
        setReport(nextReport);
        setSearches(nextSearches);
      })
      .catch(() => {
        if (active) setError("公开数据读取失败，请检查 TikHub 配置或稍后重试。");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [workspaceId]);

  if (!context || loading) return <Skeleton label="正在读取对标与评论数据" />;
  const editable = context.role === "admin" || context.role === "editor";

  async function addCompetitor(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("competitor-create"); setError(""); setMessage("");
    try {
      const created = await createCompetitorAccount(workspaceId, csrf(), {
        platform: competitorPlatform,
        name: competitorName,
        public_url: competitorUrl,
        platform_account_id: competitorId || null,
        collection_interval_hours: 24,
      });
      await collectCompetitorAccount(workspaceId, created.id, csrf());
      setCompetitorName(""); setCompetitorUrl(""); setCompetitorId("");
      setMessage("对标账号已添加，并完成第一次采集。以后每天自动更新一次。");
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "添加对标账号失败");
    } finally { setBusy(""); }
  }

  async function collect(account: CompetitorAccount) {
    setBusy(account.id); setError(""); setMessage("");
    try {
      await collectCompetitorAccount(workspaceId, account.id, csrf());
      setMessage(`${account.name} 已更新。`);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "更新失败");
    } finally { setBusy(""); }
  }

  async function analyze(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("comments"); setError(""); setMessage("");
    try {
      await analyzeCommentDemands(workspaceId, csrf(), {
        platform: commentPlatform,
        public_url: commentUrl,
        platform_content_id: commentId || null,
      });
      setCommentUrl(""); setCommentId("");
      setMessage("评论分析完成，结果已加入今日简报。这里使用规则归类，不额外消耗文字模型额度。");
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "评论分析失败");
    } finally { setBusy(""); }
  }

  async function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("search"); setError(""); setMessage("");
    try {
      await searchPublicTrends(workspaceId, csrf(), {
        platform: searchPlatform,
        keyword: searchKeyword,
      });
      setMessage("搜索完成。相同关键词 10 分钟内再次查询会直接使用已有结果，避免重复调用。");
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "热点搜索失败");
    } finally { setBusy(""); }
  }

  return <div className="space-y-5">
    {error ? <ErrorState title="当前操作没有完成" description={error} /> : null}
    {message ? <p className="rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] px-4 py-3 text-sm" role="status">{message}</p> : null}

    <Panel title="今日运营简报" description="把自己的公开数据、对标账号和评论需求汇总到一处。数据按平台分别采集，不混算。">
      {!report ? <Skeleton label="正在生成简报" /> : <>
        <dl className="grid gap-3 sm:grid-cols-3">
          <div className="rounded-xl bg-[var(--surface-muted)] p-4"><dt className="text-sm text-[var(--text-secondary)]">自己的数据更新</dt><dd className="mt-1 text-2xl font-semibold">{report.own_updates_24h}</dd></div>
          <div className="rounded-xl bg-[var(--surface-muted)] p-4"><dt className="text-sm text-[var(--text-secondary)]">正在监测的账号</dt><dd className="mt-1 text-2xl font-semibold">{report.monitored_accounts}</dd></div>
          <div className="rounded-xl bg-[var(--surface-muted)] p-4"><dt className="text-sm text-[var(--text-secondary)]">评论分析</dt><dd className="mt-1 text-2xl font-semibold">{report.comment_analyses_24h}</dd></div>
        </dl>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <section><h3 className="font-semibold">建议先做</h3><ul className="mt-2 list-disc space-y-2 pl-5 text-sm">{report.actions.map((item) => <li key={item}>{item}</li>)}</ul></section>
          <section><h3 className="font-semibold">爆款预警</h3>{report.alerts.length === 0 ? <p className="mt-2 text-sm text-[var(--text-secondary)]">暂时没有明显异常增长。至少采集两轮数据后判断会更可靠。</p> : <ul className="mt-2 space-y-2">{report.alerts.map((alert, index) => <li className="rounded-lg border border-[var(--border)] p-3" key={`${alert.kind}-${index}`}><div className="flex items-center gap-2"><StatusBadge tone="warning">{platformName(alert.platform)}</StatusBadge>{alert.public_url ? <a className="font-semibold text-[var(--brand)] underline" href={alert.public_url} rel="noreferrer" target="_blank">{alert.title}</a> : <strong>{alert.title}</strong>}</div><p className="mt-1 text-sm text-[var(--text-secondary)]">{alert.detail}</p></li>)}</ul>}</section>
        </div>
      </>}
    </Panel>

    <Panel title="关键词热点搜索" description="直接搜索抖音或小红书的公开内容，适合验证一个选题最近是否有人在讨论。">
      {editable ? <form className="grid gap-3 sm:grid-cols-[150px_1fr_auto] sm:items-end" onSubmit={search}>
        <label className="text-sm font-medium">平台<select className={control} value={searchPlatform} onChange={(event) => setSearchPlatform(event.target.value as Platform)}><option value="douyin">抖音</option><option value="xiaohongshu">小红书</option></select></label>
        <label className="text-sm font-medium">想搜索什么<input className={control} minLength={2} required value={searchKeyword} onChange={(event) => setSearchKeyword(event.target.value)} placeholder="例如：AI 视频、运营自动化" /></label>
        <button className={primaryButton} disabled={Boolean(busy)} type="submit">{busy === "search" ? "搜索中…" : "搜索公开内容"}</button>
      </form> : null}
      {searches.length === 0 ? <div className="mt-4"><EmptyState title="还没有搜索记录" description="输入一个与你账号方向相关的关键词开始搜索。" /></div> : <div className="mt-4 space-y-4">{searches.slice(0, 3).map((searchItem) => <section className="rounded-xl border border-[var(--border)] p-4" key={searchItem.id}><div className="flex items-center gap-2"><StatusBadge tone="info">{platformName(searchItem.platform)}</StatusBadge><h3 className="font-semibold">“{searchItem.keyword}”的公开内容</h3></div>{searchItem.results.length === 0 ? <p className="mt-3 text-sm text-[var(--text-secondary)]">本次没有读取到可展示的结果，可稍后重试或更换关键词。</p> : <ol className="mt-3 grid gap-2 md:grid-cols-3">{searchItem.results.slice(0, 6).map((item) => <li className="rounded-lg bg-[var(--surface-muted)] p-3 text-sm" key={item.content_id}>{item.public_url ? <a className="font-semibold text-[var(--brand)] underline" href={item.public_url} rel="noreferrer" target="_blank">{item.title}</a> : <strong>{item.title}</strong>}<p className="mt-1 text-[var(--text-secondary)]">赞 {formatCount(item.likes)} · 评论 {formatCount(item.comments)} · 收藏 {formatCount(item.favorites)}</p></li>)}</ol>}</section>)}</div>}
      <p className="mt-4 text-sm text-[var(--text-secondary)]">搜索结果只是公开样本，不等同于平台完整热度排行；重要选题仍建议结合热点榜截图核对。</p>
    </Panel>

    <Panel title="对标账号监测" description="添加同赛道账号后，每天读取一次最近公开作品。预警只和该账号自己的近期内容比较。">
      {editable ? <form className="grid gap-3 lg:grid-cols-[140px_1fr_1.4fr_1fr_auto] lg:items-end" onSubmit={addCompetitor}>
        <label className="text-sm font-medium">平台<select className={control} value={competitorPlatform} onChange={(event) => setCompetitorPlatform(event.target.value as Platform)}><option value="douyin">抖音</option><option value="xiaohongshu">小红书</option></select></label>
        <label className="text-sm font-medium">账号备注名<input className={control} required value={competitorName} onChange={(event) => setCompetitorName(event.target.value)} placeholder="例如：同赛道头部账号" /></label>
        <label className="text-sm font-medium">公开主页链接<input className={control} required type="url" value={competitorUrl} onChange={(event) => setCompetitorUrl(event.target.value)} placeholder="粘贴抖音或小红书主页链接" /></label>
        <label className="text-sm font-medium">主页 ID（识别失败时填）<input className={control} value={competitorId} onChange={(event) => setCompetitorId(event.target.value)} placeholder="通常可以留空" /></label>
        <button className={primaryButton} disabled={Boolean(busy)} type="submit">{busy === "competitor-create" ? "正在添加…" : "添加并采集"}</button>
      </form> : null}
      {competitors.length === 0 ? <div className="mt-4"><EmptyState title="还没有对标账号" description="建议先添加 1—3 个真正同赛道、内容形式接近的账号。" /></div> : <ul className="mt-4 grid gap-4 xl:grid-cols-2">{competitors.map((account) => <li className="rounded-xl border border-[var(--border)] p-4" key={account.id}>
        <div className="flex flex-wrap items-start justify-between gap-3"><div><div className="flex items-center gap-2"><StatusBadge tone={account.status === "active" ? "success" : "warning"}>{platformName(account.platform)}</StatusBadge><h3 className="font-semibold">{account.name}</h3></div><p className="mt-2 text-sm text-[var(--text-secondary)]">粉丝：{formatCount(account.follower_count)} · {account.last_collected_at ? `最近更新 ${new Date(account.last_collected_at).toLocaleString("zh-CN")}` : "尚未采集"}</p></div>{editable ? <button className={secondaryButton} disabled={Boolean(busy)} onClick={() => void collect(account)}>{busy === account.id ? "更新中…" : "立即更新"}</button> : null}</div>
        {account.latest_posts.length ? <ol className="mt-3 space-y-2">{account.latest_posts.slice(0, 3).map((post) => <li className="rounded-lg bg-[var(--surface-muted)] p-3 text-sm" key={post.content_id}>{post.public_url ? <a className="font-semibold text-[var(--brand)] underline" href={post.public_url} rel="noreferrer" target="_blank">{post.title}</a> : <strong>{post.title}</strong>}<p className="mt-1 text-[var(--text-secondary)]">赞 {formatCount(post.likes)} · 评论 {formatCount(post.comments)} · 收藏 {formatCount(post.favorites)} · 分享 {formatCount(post.shares)}</p></li>)}</ol> : <p className="mt-3 text-sm text-[var(--text-secondary)]">还没有采集到公开作品。</p>}
      </li>)}</ul>}
    </Panel>

    <Panel title="评论需求分析" description="粘贴公开作品链接，系统会把首批公开评论归为价格、教程、功能建议、对比和使用反馈。">
      {editable ? <form className="grid gap-3 lg:grid-cols-[140px_1.6fr_1fr_auto] lg:items-end" onSubmit={analyze}>
        <label className="text-sm font-medium">平台<select className={control} value={commentPlatform} onChange={(event) => setCommentPlatform(event.target.value as Platform)}><option value="douyin">抖音</option><option value="xiaohongshu">小红书</option></select></label>
        <label className="text-sm font-medium">公开作品链接<input className={control} required type="url" value={commentUrl} onChange={(event) => setCommentUrl(event.target.value)} placeholder="粘贴需要分析的作品链接" /></label>
        <label className="text-sm font-medium">作品 ID（可选）<input className={control} value={commentId} onChange={(event) => setCommentId(event.target.value)} placeholder="有 ID 时可减少一次调用" /></label>
        <button className={primaryButton} disabled={Boolean(busy)} type="submit">{busy === "comments" ? "分析中…" : "分析评论"}</button>
      </form> : null}
      {analyses.length === 0 ? <div className="mt-4"><EmptyState title="还没有评论分析" description="可先选择自己或对标账号的一条近期作品进行分析。" /></div> : <ul className="mt-4 space-y-4">{analyses.slice(0, 5).map((analysis) => <li className="rounded-xl border border-[var(--border)] p-4" key={analysis.id}><div className="flex flex-wrap items-center gap-2"><StatusBadge tone="info">{platformName(analysis.platform)}</StatusBadge><strong>分析了 {analysis.comment_count} 条公开评论</strong></div><div className="mt-3 grid gap-3 md:grid-cols-2">{analysis.themes.map((theme) => <section className="rounded-lg bg-[var(--surface-muted)] p-3" key={theme.theme}><h4 className="font-medium">{theme.theme}（{theme.count}）</h4><ul className="mt-1 space-y-1 text-sm text-[var(--text-secondary)]">{theme.examples.map((example) => <li key={example}>“{example}”</li>)}</ul></section>)}</div>{analysis.top_questions.length ? <p className="mt-3 text-sm"><strong>可直接转成选题的问题：</strong>{analysis.top_questions.slice(0, 3).join("；")}</p> : null}</li>)}</ul>}
      <p className="mt-4 text-sm text-[var(--text-secondary)]">这里只分析公开评论中的需求信号，不代表全部用户观点；需要更多样本时可分批重复分析。</p>
    </Panel>
  </div>;
}
