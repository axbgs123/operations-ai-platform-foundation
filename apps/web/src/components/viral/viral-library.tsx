"use client";

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


const CATEGORY_LABELS = {
  traffic: "流量爆款",
  engagement: "互动爆款",
  growth: "涨粉爆款",
  conversion: "转化爆款",
} as const;

type ViralCategory = keyof typeof CATEGORY_LABELS;
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

export function ViralLibrary({
  workspaceId,
  accountId,
}: {
  workspaceId: string;
  accountId: string;
}) {
  const [candidates, setCandidates] = useState<ViralCandidateData[]>([]);
  const [items, setItems] = useState<ViralLibraryItemData[]>([]);
  const [rules, setRules] = useState<RuleDraft[]>(() => ruleDrafts());
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

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

  return (
    <section className="space-y-8">
      <header>
        <p className="text-sm font-medium text-fuchsia-300">账号级可复用策略资产</p>
        <h1 className="mt-2 text-3xl font-semibold">爆款候选与素材库</h1>
        <p className="mt-3 max-w-3xl text-slate-400">
          系统只推荐样本量不少于 10、进入账号历史前 10% 且达到绝对门槛的内容；
          只有人工确认的素材才会开放给生成模块。
        </p>
      </header>

      {error ? <p className="rounded-xl bg-rose-950/60 p-4 text-rose-300">{error}</p> : null}
      {message ? <p className="rounded-xl bg-emerald-950/60 p-4 text-emerald-300">{message}</p> : null}

      <form
        className="grid gap-4 rounded-3xl border border-slate-800 bg-slate-900 p-6 sm:grid-cols-2 lg:grid-cols-6"
        onSubmit={configureAndEvaluate}
      >
        <fieldset className="space-y-3 sm:col-span-2 lg:col-span-6">
          <legend className="font-semibold">完整门槛规则集（保存时整体替换）</legend>
          {rules.map((rule, index) => (
            <div className="grid gap-3 rounded-xl bg-slate-950 p-3 sm:grid-cols-[1fr_1fr_1fr_auto]" key={rule.id}>
              <label>
                第 {index + 1} 条候选类别
                <select
                  className="mt-1 w-full rounded-lg bg-slate-900 px-3 py-2"
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
                  className="mt-1 w-full rounded-lg bg-slate-900 px-3 py-2"
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
                  className="mt-1 w-full rounded-lg bg-slate-900 px-3 py-2"
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
            className="rounded-lg border border-cyan-700 px-4 py-2 text-cyan-300"
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
          <select className="mt-2 w-full rounded-xl bg-slate-950 px-3 py-3" defaultValue="video" name="contentType">
            <option value="video">视频</option>
            <option value="image_text">图文</option>
          </select>
        </label>
        <label>
          数据成熟度
          <select className="mt-2 w-full rounded-xl bg-slate-950 px-3 py-3" defaultValue="24h" name="maturityBucket">
            <option value="1h">1 小时</option>
            <option value="24h">24 小时</option>
            <option value="72h">72 小时</option>
            <option value="7d">7 天</option>
          </select>
        </label>
        <button className="self-end rounded-xl bg-cyan-400 px-4 py-3 font-semibold text-slate-950 disabled:opacity-50" disabled={busyId === "evaluation"} type="submit">
          保存门槛并生成候选
        </button>
      </form>

      <div className="space-y-4">
        <div>
          <p className="text-sm text-slate-400">待人工判断</p>
          <h2 className="text-2xl font-semibold">爆款候选</h2>
        </div>
        {recommended.length === 0 ? (
          <p className="rounded-2xl border border-slate-800 bg-slate-900 p-5 text-slate-400">
            暂无待确认候选。
          </p>
        ) : recommended.map((candidate) => (
          <article
            className="grid gap-6 rounded-3xl border border-slate-800 bg-slate-900 p-6 lg:grid-cols-[1fr_1.1fr]"
            key={candidate.id}
          >
            <div className="space-y-3">
              <p className="text-sm font-medium text-fuchsia-300">
                {CATEGORY_LABELS[candidate.category]}
              </p>
              <h3 className="text-xl font-semibold">{candidate.title}</h3>
              <p className="text-sm text-slate-300">{candidate.reason}</p>
              <p className="text-xs text-slate-500">
                {candidate.platform} / {candidate.content_type} / {candidate.maturity_bucket} · 比较范围 {new Date(candidate.comparison_started_at).toLocaleString("zh-CN")} — {new Date(candidate.comparison_ended_at).toLocaleString("zh-CN")}
              </p>
              <dl className="grid grid-cols-2 gap-3 text-sm">
                <div className="rounded-xl bg-slate-950 p-3">
                  <dt className="text-slate-500">命中指标</dt>
                  <dd className="mt-1 font-medium">{candidate.metric_key}: {candidate.actual_value}</dd>
                </div>
                <div className="rounded-xl bg-slate-950 p-3">
                  <dt className="text-slate-500">冻结证据</dt>
                  <dd className="mt-1 font-medium">
                    样本 {candidate.sample_count} · 历史分位 {(candidate.percentile * 100).toFixed(1)}% · 门槛版本 v{candidate.threshold_profile_version}
                  </dd>
                </div>
              </dl>
            </div>
            <form className="space-y-4" onSubmit={(event) => confirm(event, candidate.id)}>
              <label className="block">
                策略标签
                <input className="mt-2 w-full rounded-xl bg-slate-950 px-4 py-3" name="strategyTags" placeholder="强钩子, 结果前置" required />
              </label>
              <label className="block">
                适用场景
                <input className="mt-2 w-full rounded-xl bg-slate-950 px-4 py-3" name="scenarios" placeholder="新品讲解, 教程" required />
              </label>
              <label className="block">
                结构总结
                <textarea className="mt-2 min-h-24 w-full rounded-xl bg-slate-950 px-4 py-3" name="summary" required />
              </label>
              <button className="rounded-xl bg-fuchsia-400 px-5 py-3 font-semibold text-slate-950 disabled:opacity-50" disabled={busyId === candidate.id} type="submit">
                确认进入素材库
              </button>
            </form>
          </article>
        ))}
      </div>

      <div className="space-y-4">
        <div>
          <p className="text-sm text-slate-400">包含已撤销的完整历史</p>
          <h2 className="text-2xl font-semibold">已确认素材</h2>
        </div>
        {items.length === 0 ? (
          <p className="rounded-2xl border border-slate-800 bg-slate-900 p-5 text-slate-400">
            尚无人工确认素材。
          </p>
        ) : items.map((item) => (
          <article className="rounded-3xl border border-slate-800 bg-slate-900 p-6" key={item.id}>
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="space-y-2">
                <p className={item.generation_eligible ? "text-emerald-300" : "text-slate-500"}>
                  {item.generation_eligible
                    ? "可供生成使用"
                    : item.active
                      ? "内容已删除，暂不可供生成使用"
                      : "已撤销，仅保留历史"}
                </p>
                <h3 className="text-xl font-semibold">{item.title}</h3>
                <p className="text-slate-300">{item.structure_summary}</p>
                <p className="text-sm text-slate-400">
                  策略：{item.strategy_tags.join(" · ")}　场景：{item.applicable_scenarios.join(" · ")}
                </p>
                {!item.active && item.revocation_reason ? (
                  <p className="text-sm text-amber-300">撤销原因：{item.revocation_reason}</p>
                ) : null}
              </div>
              {item.active ? (
                <form className="flex flex-wrap items-end gap-3" onSubmit={(event) => revoke(event, item.id)}>
                  <label>
                    撤销原因
                    <input className="mt-2 block rounded-xl bg-slate-950 px-4 py-3" name="reason" required />
                  </label>
                  <button className="rounded-xl border border-amber-400 px-4 py-3 font-semibold text-amber-300 disabled:opacity-50" disabled={busyId === item.id} type="submit">
                    撤销素材
                  </button>
                </form>
              ) : null}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
