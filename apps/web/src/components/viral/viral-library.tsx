"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { FormEvent, useCallback, useEffect, useState } from "react";

import {
  configureViralThresholds,
  confirmViralCandidate,
  evaluateViralCandidates,
  listViralCandidates,
  listViralLibrary,
  readViralThresholds,
  revokeViralLibraryItem,
  ViralCandidateData,
  ViralLibraryItemData,
} from "@/lib/viral-api";
import { GuidedPageHeader } from "@/components/workbench/guided-page-header";
import { EmptyState, StatusBadge } from "@/components/workbench/ui";
import { useWorkbenchShellContext } from "@/components/workbench/workspace-shell";

const viralCandidateExplanation = {
  simple: "候选只是这个账号里相对表现较好的内容；人工确认后，生成时才能把它作为参考。",
  professional: "候选按单账号动态基准产生；未确认候选不得进入生成引用。",
};

const CATEGORY_LABELS = {
  traffic: "流量爆款",
  engagement: "互动爆款",
  growth: "涨粉爆款",
  conversion: "转化爆款",
} as const;

type ViralCategory = keyof typeof CATEGORY_LABELS;
type AccountOption = {
  account_id: string;
  platform: "douyin" | "xiaohongshu";
  name: string;
};
type RuleDraft = {
  id: string;
  category: ViralCategory;
  metricKey: string;
  minimumValue: string;
};
let nextDraftId = 1;

function ruleDrafts(
  rules: Array<{ category: ViralCategory; metric_key: string; minimum_value: number | string }> = [],
): RuleDraft[] {
  if (rules.length === 0) {
    return [{ id: "rule-0", category: "traffic", metricKey: "views", minimumValue: "" }];
  }
  return rules.map((rule, index) => ({
    id: `rule-${index}`,
    category: rule.category,
    metricKey: rule.metric_key,
    minimumValue: String(rule.minimum_value),
  }));
}

function labels(value: string) {
  return value
    .split(/[,，]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function resolveViralAccount(
  accounts: readonly AccountOption[],
  rawPlatform: string | null,
  rawAccount: string | null,
): AccountOption | undefined {
  if (
    rawPlatform !== null
    && rawPlatform !== "douyin"
    && rawPlatform !== "xiaohongshu"
  ) {
    return undefined;
  }
  return accounts.find((account) =>
    account.account_id === rawAccount
    && (rawPlatform === null || account.platform === rawPlatform)
  );
}

export function ViralLibrary({
  workspaceId,
  accountId,
  role,
}: {
  workspaceId: string;
  accountId: string;
  role?: "admin" | "editor" | "viewer";
}) {
  const [candidates, setCandidates] = useState<ViralCandidateData[]>([]);
  const [items, setItems] = useState<ViralLibraryItemData[]>([]);
  const [rules, setRules] = useState<RuleDraft[]>(() => ruleDrafts());
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const shellContext = useWorkbenchShellContext();

  const reload = useCallback(async () => {
    try {
      const [nextCandidates, nextItems, threshold] = await Promise.all([
        listViralCandidates(workspaceId, accountId),
        listViralLibrary(workspaceId, accountId),
        readViralThresholds(workspaceId, accountId),
      ]);
      setCandidates(nextCandidates);
      setItems(nextItems);
      setRules(ruleDrafts(threshold?.rules));
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "素材库加载失败");
    }
  }, [accountId, workspaceId]);

  useEffect(() => {
    let active = true;
    Promise.all([
      listViralCandidates(workspaceId, accountId),
      listViralLibrary(workspaceId, accountId),
      readViralThresholds(workspaceId, accountId),
    ])
      .then(([nextCandidates, nextItems, threshold]) => {
        if (!active) return;
        setCandidates(nextCandidates);
        setItems(nextItems);
        setRules(ruleDrafts(threshold?.rules));
        setError("");
      })
      .catch((caught: unknown) => {
        if (active) {
          setError(caught instanceof Error ? caught.message : "素材库加载失败");
        }
      });
    return () => { active = false; };
  }, [accountId, workspaceId]);

  const csrf = () => sessionStorage.getItem("workspace_csrf") ?? "";

  async function configureAndEvaluate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const enabledRules = rules.map((rule) => ({
        category: rule.category,
        metric_key: rule.metricKey,
        minimum_value: Number(rule.minimumValue),
      }));
    if (enabledRules.length === 0) {
      setError("至少启用一个候选类别");
      return;
    }
    const form = new FormData(event.currentTarget);
    setBusyId("evaluation");
    setError("");
    setMessage("");
    try {
      await configureViralThresholds(
        workspaceId,
        accountId,
        { rules: enabledRules },
        csrf(),
      );
      const evaluated = await evaluateViralCandidates(
        workspaceId,
        accountId,
        {
          content_type: String(form.get("contentType")) as "video" | "image_text",
          maturity_bucket: String(form.get("maturityBucket")) as "1h" | "24h" | "72h" | "7d",
        },
        csrf(),
      );
      setMessage(`门槛已保存，本次生成 ${evaluated.length} 条候选`);
      await reload();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "候选生成失败");
    } finally {
      setBusyId("");
    }
  }

  async function confirm(
    event: FormEvent<HTMLFormElement>,
    candidateId: string,
  ) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusyId(candidateId);
    setError("");
    setMessage("");
    try {
      await confirmViralCandidate(
        workspaceId,
        candidateId,
        {
          strategy_tags: labels(String(form.get("strategyTags") ?? "")),
          applicable_scenarios: labels(String(form.get("scenarios") ?? "")),
          structure_summary: String(form.get("summary") ?? "").trim(),
        },
        csrf(),
      );
      setMessage("候选已由人工确认并进入爆款素材库");
      await reload();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "确认失败");
    } finally {
      setBusyId("");
    }
  }

  async function revoke(event: FormEvent<HTMLFormElement>, itemId: string) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusyId(itemId);
    setError("");
    setMessage("");
    try {
      await revokeViralLibraryItem(
        workspaceId,
        itemId,
        String(form.get("reason") ?? "").trim(),
        csrf(),
      );
      setMessage("素材已撤销；历史记录与审计信息仍然保留");
      await reload();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "撤销失败");
    } finally {
      setBusyId("");
    }
  }

  const recommended = candidates.filter((item) => item.status === "recommended");
  const canWrite = (role ?? shellContext?.role ?? "admin") !== "viewer";

  return (
    <section className="space-y-8">
      <GuidedPageHeader
        context={viralCandidateExplanation}
        pageId="viralLibrary"
        title="爆款候选与素材库"
      />
      <aside className="rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-950" role="note">
        <p className="font-semibold">账号范围：{accountId}</p>
        <p className="mt-1">历史高分位只表示相关性，不代表确定因果</p>
        <p className="mt-1">爆款结构与账号风格分开维护，不会自动成为风格样本。</p>
      </aside>
      {!canWrite ? (
        <p className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">
          查看者可查看资产，不能确认、撤销或重新评估
        </p>
      ) : null}

      {error ? <p className="rounded-xl border border-red-300 bg-red-50 p-4 text-red-950" role="alert">{error}</p> : null}
      {message ? <p className="rounded-xl border border-emerald-300 bg-emerald-50 p-4 text-emerald-950" role="status">{message}</p> : null}

      {canWrite ? <form
        className="grid gap-4 rounded-xl border bg-white p-5 sm:grid-cols-2 lg:grid-cols-6"
        onSubmit={configureAndEvaluate}
      >
        <fieldset className="space-y-3 sm:col-span-2 lg:col-span-6">
          <legend className="font-semibold">完整门槛规则集（保存时整体替换）</legend>
          {rules.map((rule, index) => (
            <div className="grid gap-3 rounded-xl border bg-slate-50 p-3 sm:grid-cols-[1fr_1fr_1fr_auto]" key={rule.id}>
              <label>
                第 {index + 1} 条候选类别
                <select
                  className="mt-1 w-full rounded-lg border bg-white px-3 py-2"
                  onChange={(event) => setRules((current) => current.map(
                    (item, itemIndex) => itemIndex === index
                      ? { ...item, category: event.target.value as ViralCategory }
                      : item,
                  ))}
                  value={rule.category}
                >
                  {Object.entries(CATEGORY_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>{label}</option>
                  ))}
                </select>
              </label>
              <label>
                第 {index + 1} 条指标键
                <input
                  className="mt-1 w-full rounded-lg border bg-white px-3 py-2"
                  onChange={(event) => setRules((current) => current.map(
                    (item, itemIndex) => itemIndex === index
                      ? { ...item, metricKey: event.target.value }
                      : item,
                  ))}
                  required
                  value={rule.metricKey}
                />
              </label>
              <label>
                第 {index + 1} 条绝对最低门槛
                <input
                  className="mt-1 w-full rounded-lg border bg-white px-3 py-2"
                  min="0"
                  onChange={(event) => setRules((current) => current.map(
                    (item, itemIndex) => itemIndex === index
                      ? { ...item, minimumValue: event.target.value }
                      : item,
                  ))}
                  required
                  step="any"
                  type="number"
                  value={rule.minimumValue}
                />
              </label>
              <button
                className="self-end rounded-lg border border-slate-700 px-3 py-2 text-slate-300 disabled:opacity-40"
                disabled={rules.length === 1}
                onClick={() => setRules((current) => current.filter((_, itemIndex) => itemIndex !== index))}
                type="button"
              >
                删除第 {index + 1} 条
              </button>
            </div>
          ))}
          <button
            className="rounded-lg border border-[var(--brand)] px-4 py-2 text-[var(--brand)]"
            onClick={() => setRules((current) => [
              ...current,
              {
                id: `draft-${nextDraftId++}`,
                category: "traffic",
                metricKey: "views",
                minimumValue: "",
              },
            ])}
            type="button"
          >
            添加门槛规则
          </button>
        </fieldset>
        <label>
          内容类型
          <select className="mt-2 w-full rounded-lg border bg-white px-3 py-3" defaultValue="video" name="contentType">
            <option value="video">视频</option>
            <option value="image_text">图文</option>
          </select>
        </label>
        <label>
          数据成熟度
          <select className="mt-2 w-full rounded-lg border bg-white px-3 py-3" defaultValue="24h" name="maturityBucket">
            <option value="1h">1 小时</option>
            <option value="24h">24 小时</option>
            <option value="72h">72 小时</option>
            <option value="7d">7 天</option>
          </select>
        </label>
        <button className="self-end rounded-lg bg-[var(--brand)] px-4 py-3 font-semibold text-white disabled:opacity-50" disabled={busyId === "evaluation"} type="submit">
          保存门槛并生成候选
        </button>
      </form> : null}

      <section aria-label="爆款候选" className="space-y-4" data-mobile-layout="cards">
        <div>
          <p className="text-sm text-slate-400">待人工判断</p>
          <h2 className="text-2xl font-semibold">爆款候选</h2>
        </div>
        {recommended.length === 0 ? (
          <p className="rounded-xl border bg-white p-5 text-[var(--text-secondary)]">
            暂无待确认候选。
          </p>
        ) : recommended.map((candidate) => (
          <article
            className="grid gap-6 rounded-xl border border-dashed border-amber-400 bg-amber-50/40 p-5 lg:grid-cols-[1fr_1.1fr]"
            key={candidate.id}
          >
            <div className="space-y-3">
              <StatusBadge tone="warning">候选，尚未进入素材库</StatusBadge>
              <p className="text-sm font-medium text-amber-900">{CATEGORY_LABELS[candidate.category]}</p>
              <h3 className="text-xl font-semibold">{candidate.title}</h3>
              <Link
                className="text-sm font-semibold text-[var(--brand)]"
                href={`/workspaces/${workspaceId}/contents/${candidate.content_id}?${new URLSearchParams({
                  tab: "overview",
                  platform: candidate.platform,
                  account: candidate.account_id,
                  returnTo: `/workspaces/${workspaceId}/viral-library?${new URLSearchParams({
                    platform: candidate.platform,
                    account: candidate.account_id,
                  })}`,
                })}`}
              >
                查看候选内容
              </Link>
              <p className="text-sm text-[var(--text-secondary)]">{candidate.reason}</p>
              <p className="text-xs text-[var(--text-secondary)]">
                {candidate.platform} / {candidate.content_type} / {candidate.maturity_bucket} · 比较范围 {new Date(candidate.comparison_started_at).toLocaleString("zh-CN")} — {new Date(candidate.comparison_ended_at).toLocaleString("zh-CN")}
              </p>
              <p className="text-sm">数据成熟度：{candidate.maturity_bucket}</p>
              <p className="text-sm">候选产生时间：当前记录未提供</p>
              <p className="text-sm font-medium text-amber-900">候选不能被生成中心引用</p>
              <dl className="grid grid-cols-2 gap-3 text-sm">
                <div className="rounded-xl border bg-white p-3">
                  <dt className="text-slate-500">命中指标</dt>
                  <dd className="mt-1 font-medium">{candidate.metric_key}: {candidate.actual_value}</dd>
                </div>
                <div className="rounded-xl border bg-white p-3">
                  <dt className="text-slate-500">冻结证据</dt>
                  <dd className="mt-1 font-medium">
                    样本 {candidate.sample_count} · 历史分位 {(candidate.percentile * 100).toFixed(1)}% · 门槛版本 v{candidate.threshold_profile_version}
                  </dd>
                </div>
              </dl>
            </div>
            {canWrite ? <form className="space-y-4" onSubmit={(event) => confirm(event, candidate.id)}>
              <label className="block">
                策略标签
                <input className="mt-2 w-full rounded-lg border bg-white px-4 py-3" name="strategyTags" placeholder="强钩子, 结果前置" required />
              </label>
              <label className="block">
                适用场景
                <input className="mt-2 w-full rounded-lg border bg-white px-4 py-3" name="scenarios" placeholder="新品讲解, 教程" required />
              </label>
              <label className="block">
                结构总结
                <textarea className="mt-2 min-h-24 w-full rounded-lg border bg-white px-4 py-3" name="summary" required />
              </label>
              <button className="rounded-lg bg-[var(--brand)] px-5 py-3 font-semibold text-white disabled:opacity-50" disabled={busyId === candidate.id} type="submit">
                确认进入素材库
              </button>
            </form> : (
              <p className="self-start rounded-lg border bg-white p-4 text-sm">
                人工确认操作对查看者不可用。
              </p>
            )}
          </article>
        ))}
      </section>

      <section aria-label="已确认素材" className="space-y-4" data-mobile-layout="cards" role="region">
        <div>
          <p className="text-sm text-slate-400">包含已撤销的完整历史</p>
          <h2 className="text-2xl font-semibold">已确认素材</h2>
        </div>
        {items.length === 0 ? (
          <p className="rounded-xl border bg-white p-5 text-[var(--text-secondary)]">
            尚无人工确认素材。
          </p>
        ) : items.map((item) => (
          <article className="rounded-xl border border-emerald-200 bg-white p-5" key={item.id}>
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="space-y-2">
                <p className={item.generation_eligible ? "font-semibold text-emerald-800" : "text-[var(--text-secondary)]"}>
                  {item.generation_eligible
                    ? "可供生成使用"
                    : item.active
                      ? "内容已删除，暂不可供生成使用"
                      : "已撤销，仅保留历史"}
                </p>
                <h3 className="text-xl font-semibold">{item.title}</h3>
                <Link
                  className="text-sm font-semibold text-[var(--brand)]"
                  href={`/workspaces/${workspaceId}/contents/${item.content_id}?${new URLSearchParams({
                    tab: "overview",
                    account: item.account_id,
                    returnTo: `/workspaces/${workspaceId}/viral-library?account=${item.account_id}`,
                  })}`}
                >
                  查看已确认内容
                </Link>
                <p className="text-slate-300">{item.structure_summary}</p>
                <p className="text-sm text-slate-400">
                  策略：{item.strategy_tags.join(" · ")}　场景：{item.applicable_scenarios.join(" · ")}
                </p>
                <p className="text-sm text-[var(--text-secondary)]">
                  适用账号：{item.account_id} · 适用栏目/场景：{item.applicable_scenarios.join(" · ")}
                </p>
                <p className="text-sm text-[var(--text-secondary)]">
                  确认人：{item.confirmed_by ?? "当前记录未提供"} · 确认时间：{new Date(item.confirmed_at).toLocaleString("zh-CN")}
                </p>
                <p className="text-sm text-[var(--text-secondary)]">
                  生成引用次数：当前记录未提供
                </p>
                {!item.active && item.revocation_reason ? (
                  <p className="text-sm text-amber-900">撤销原因：{item.revocation_reason}</p>
                ) : null}
              </div>
              {item.active && canWrite ? (
                <form className="flex flex-wrap items-end gap-3" onSubmit={(event) => revoke(event, item.id)}>
                  <label>
                    撤销原因
                    <input className="mt-2 block rounded-lg border bg-white px-4 py-3" name="reason" required />
                  </label>
                  <button className="rounded-lg border border-amber-600 px-4 py-3 font-semibold text-amber-900 disabled:opacity-50" disabled={busyId === item.id} type="submit">
                    撤销素材
                  </button>
                </form>
              ) : null}
            </div>
          </article>
        ))}
      </section>
    </section>
  );
}

export function ViralLibraryPage({
  workspaceId,
}: {
  workspaceId: string;
}) {
  const context = useWorkbenchShellContext();
  const searchParams = useSearchParams();
  if (!context) {
    return (
      <EmptyState
        description="工作区范围尚未加载，请稍后重试。"
        title="无法读取账号范围"
      />
    );
  }
  const rawPlatform = searchParams.get("platform");
  const platform = rawPlatform === "douyin" || rawPlatform === "xiaohongshu"
    ? rawPlatform
    : undefined;
  const rawAccount = searchParams.get("account") ?? searchParams.get("account_id");
  const account = resolveViralAccount(
    context.accounts,
    platform ?? (rawPlatform === null ? null : rawPlatform),
    rawAccount,
  );
  if (!account) {
    const visibleAccounts = platform
      ? context.accounts.filter((item) => item.platform === platform)
      : context.accounts;
    return (
      <div className="mx-auto max-w-6xl space-y-6">
        <GuidedPageHeader
          context={viralCandidateExplanation}
          pageId="viralLibrary"
        />
        {visibleAccounts.length ? (
          <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {visibleAccounts.map((item) => {
              const query = new URLSearchParams({
                platform: item.platform,
                account: item.account_id,
              });
              return (
                <li className="rounded-xl border bg-white p-5" key={item.account_id}>
                  <StatusBadge tone={item.platform === "douyin" ? "info" : "warning"}>
                    {item.platform === "douyin" ? "抖音" : "小红书"}
                  </StatusBadge>
                  <h2 className="mt-3 font-semibold">{item.name}</h2>
                  <Link
                    className="mt-4 inline-flex rounded-lg bg-[var(--brand)] px-4 py-2 text-sm font-semibold text-white"
                    href={`/workspaces/${workspaceId}/viral-library?${query}`}
                  >
                    查看账号素材
                  </Link>
                </li>
              );
            })}
          </ul>
        ) : (
          <EmptyState
            description="当前平台还没有可用账号。下一步：在工作区设置中创建账号。"
            title="没有可选账号"
          />
        )}
      </div>
    );
  }
  return (
    <div className="mx-auto max-w-7xl">
      <ViralLibrary
        accountId={account.account_id}
        role={context.role}
        workspaceId={workspaceId}
      />
    </div>
  );
}
