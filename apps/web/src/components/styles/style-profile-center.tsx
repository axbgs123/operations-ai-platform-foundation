"use client";

import { useEffect, useMemo, useState } from "react";

import {
  confirmStyleProfile,
  extractStyleProfile,
  listStyleCandidates,
  listStyleProfiles,
  listStyleSamples,
  listStyleScopes,
  selectStyleSample,
  StyleCandidateData,
  StyleProfileData,
  StyleSampleData,
  StyleScopeData,
} from "@/lib/style-api";


const SECTION_LABELS: Record<string, string> = {
  title: "标题",
  copy: "文案",
  cover: "封面",
  prohibited: "禁止项",
};

function stringValues(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function labelValues(value: string): string[] {
  return value
    .split(/[,，]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function StyleProfileCenter({
  workspaceId,
  accountId,
  columnCampaignId = null,
}: {
  workspaceId: string;
  accountId: string;
  columnCampaignId?: string | null;
}) {
  const [candidates, setCandidates] = useState<StyleCandidateData[]>([]);
  const [samples, setSamples] = useState<StyleSampleData[]>([]);
  const [profiles, setProfiles] = useState<StyleProfileData[]>([]);
  const [scopes, setScopes] = useState<StyleScopeData[]>([]);
  const [inheritTitle, setInheritTitle] = useState(true);
  const [inheritCopy, setInheritCopy] = useState(true);
  const [inheritCover, setInheritCover] = useState(true);
  const [prohibitedExpressions, setProhibitedExpressions] = useState("");
  const [prohibitedColors, setProhibitedColors] = useState("");
  const [prohibitedLayouts, setProhibitedLayouts] = useState("");
  const [prohibitedVisualStyles, setProhibitedVisualStyles] = useState("");
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    Promise.all([
      listStyleCandidates(workspaceId, accountId, columnCampaignId),
      listStyleSamples(workspaceId, accountId, columnCampaignId),
      listStyleProfiles(workspaceId, accountId),
      listStyleScopes(workspaceId, accountId),
    ])
      .then(([nextCandidates, nextSamples, nextProfiles, nextScopes]) => {
        if (!active) return;
        setCandidates(nextCandidates);
        setSamples(nextSamples);
        setProfiles(nextProfiles);
        setScopes(nextScopes);
        const scopeKey = columnCampaignId ? `column:${columnCampaignId}` : "account";
        const currentProfile = nextProfiles
          .filter((profile) => profile.scope_key === scopeKey)
          .sort((left, right) => right.version - left.version)[0];
        const current = recordValue(currentProfile?.style.prohibited);
        setProhibitedExpressions(stringValues(current.expressions).join(", "));
        setProhibitedColors(stringValues(current.colors).join(", "));
        setProhibitedLayouts(stringValues(current.layouts).join(", "));
        setProhibitedVisualStyles(stringValues(current.visual_styles).join(", "));
      })
      .catch((caught: unknown) => {
        if (active) {
          setError(caught instanceof Error ? caught.message : "风格档案加载失败");
        }
      });
    return () => { active = false; };
  }, [accountId, columnCampaignId, workspaceId]);

  const latestProfile = useMemo(
    () => profiles
      .filter((profile) => profile.scope_key === (
        columnCampaignId ? `column:${columnCampaignId}` : "account"
      ))
      .sort((left, right) => right.version - left.version)[0],
    [columnCampaignId, profiles],
  );
  const csrf = () => sessionStorage.getItem("workspace_csrf") ?? "";

  async function chooseSample(candidate: StyleCandidateData) {
    setBusy(candidate.content_id);
    setError("");
    try {
      const selected = await selectStyleSample(
        workspaceId,
        accountId,
        candidate.content_id,
        csrf(),
        columnCampaignId,
      );
      setSamples((current) => [...current, selected]);
      setCandidates((current) => current.map((item) => (
        item.content_id === candidate.content_id ? { ...item, selected: true } : item
      )));
      setMessage("已加入风格样本；重新提取后才会形成待确认版本");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "样本选择失败");
    } finally {
      setBusy("");
    }
  }

  async function extract() {
    setBusy("extract");
    setError("");
    try {
      const profile = await extractStyleProfile(
        workspaceId,
        accountId,
        csrf(),
        columnCampaignId,
        {
          expressions: labelValues(prohibitedExpressions),
          colors: labelValues(prohibitedColors),
          layouts: labelValues(prohibitedLayouts),
          visual_styles: labelValues(prohibitedVisualStyles),
        },
      );
      setProfiles((current) => [
        ...current.filter((item) => item.id !== profile.id),
        profile,
      ]);
      setMessage(`已提取 v${profile.version}，确认前不会生效`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "风格提取失败");
    } finally {
      setBusy("");
    }
  }

  async function confirm(profile: StyleProfileData) {
    setBusy(profile.id);
    setError("");
    try {
      const confirmed = await confirmStyleProfile(workspaceId, profile.id, csrf());
      setProfiles((current) => current.map((item) => (
        item.id === confirmed.id ? confirmed : item
      )));
      setMessage(`v${confirmed.version} 已确认并启用`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "风格确认失败");
    } finally {
      setBusy("");
    }
  }

  const titleStyle = recordValue(latestProfile?.style.title);
  const copyStyle = recordValue(latestProfile?.style.copy);
  const coverStyle = recordValue(latestProfile?.style.cover);
  const prohibited = recordValue(latestProfile?.style.prohibited);
  const changedSections = stringValues(latestProfile?.diff.changed_sections);
  const baseVersion = latestProfile?.diff.base_version;
  const allDisabled = !inheritTitle && !inheritCopy && !inheritCover;

  return (
    <section className="space-y-8">
      <header>
        <p className="text-sm font-medium text-cyan-300">人工选择 · 版本确认 · 默认继承</p>
        <h1 className="mt-2 text-3xl font-semibold">账号风格中心</h1>
        <p className="mt-3 max-w-3xl text-slate-400">
          最近内容和爆款只作为候选，不会自动进入品牌风格；只有人工选择并确认的版本才会生效。
        </p>
        {columnCampaignId ? (
          <p className="mt-2 text-sm text-fuchsia-300">当前正在维护栏目/活动覆盖风格</p>
        ) : null}
      </header>

      <nav className="rounded-3xl border border-slate-800 bg-slate-900 p-5" aria-label="风格档案范围">
        <p className="text-sm font-medium text-slate-300">选择账号或栏目/活动范围</p>
        <div className="mt-3 flex flex-wrap gap-2">
          <a
            className={`rounded-xl px-4 py-2 ${columnCampaignId ? "bg-slate-800" : "bg-cyan-400 text-slate-950"}`}
            href={`/workspaces/${workspaceId}/styles/${accountId}`}
          >
            账号默认
          </a>
          {scopes.map((scope) => (
            <a
              className={`rounded-xl px-4 py-2 ${columnCampaignId === scope.id ? "bg-fuchsia-400 text-slate-950" : "bg-slate-800"}`}
              href={`/workspaces/${workspaceId}/styles/${accountId}?columnCampaignId=${scope.id}`}
              key={scope.id}
            >
              {scope.name}
            </a>
          ))}
        </div>
      </nav>

      {error ? <p className="rounded-xl bg-rose-950/60 p-4 text-rose-300">{error}</p> : null}
      {message ? <p className="rounded-xl bg-emerald-950/60 p-4 text-emerald-300">{message}</p> : null}

      <section className="rounded-3xl border border-slate-800 bg-slate-900 p-6">
        <div className="mb-6">
          <h2 className="text-xl font-semibold">显式禁止项</h2>
          <p className="mt-1 text-sm text-slate-400">
            禁止项只采用人工填写内容，不会由模型推测。多个值请用逗号分隔。
          </p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <label className="text-sm text-slate-300">
              禁止表达
              <input
                className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2"
                onChange={(event) => setProhibitedExpressions(event.target.value)}
                value={prohibitedExpressions}
              />
            </label>
            <label className="text-sm text-slate-300">
              禁止颜色
              <input
                className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2"
                onChange={(event) => setProhibitedColors(event.target.value)}
                value={prohibitedColors}
              />
            </label>
            <label className="text-sm text-slate-300">
              禁止版式
              <input
                className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2"
                onChange={(event) => setProhibitedLayouts(event.target.value)}
                value={prohibitedLayouts}
              />
            </label>
            <label className="text-sm text-slate-300">
              禁止视觉风格
              <input
                className="mt-1 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2"
                onChange={(event) => setProhibitedVisualStyles(event.target.value)}
                value={prohibitedVisualStyles}
              />
            </label>
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold">生成时的风格继承</h2>
            <p className="mt-1 text-sm text-slate-400">默认全部开启，也可以按内容类型独立关闭。</p>
          </div>
          <button
            className="rounded-xl border border-cyan-500 px-4 py-2 text-cyan-200"
            onClick={() => {
              setInheritTitle(true);
              setInheritCopy(true);
              setInheritCover(true);
            }}
            type="button"
          >
            一键沿用全部风格
          </button>
        </div>
        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          <label className="rounded-xl bg-slate-950 p-4">
            <input checked={inheritTitle} onChange={(event) => setInheritTitle(event.target.checked)} type="checkbox" />
            <span className="ml-2">沿用标题风格</span>
          </label>
          <label className="rounded-xl bg-slate-950 p-4">
            <input checked={inheritCopy} onChange={(event) => setInheritCopy(event.target.checked)} type="checkbox" />
            <span className="ml-2">沿用文案风格</span>
          </label>
          <label className="rounded-xl bg-slate-950 p-4">
            <input checked={inheritCover} onChange={(event) => setInheritCover(event.target.checked)} type="checkbox" />
            <span className="ml-2">沿用封面风格</span>
          </label>
        </div>
        {allDisabled ? (
          <p className="mt-4 text-amber-300">当前生成上下文不会引用任何历史风格</p>
        ) : null}
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-3xl border border-slate-800 bg-slate-900 p-6">
          <h2 className="text-xl font-semibold">已选样本来源</h2>
          <ul className="mt-4 space-y-3">
            {samples.map((sample) => (
              <li className="rounded-xl bg-slate-950 p-4" key={sample.id}>
                <p className="font-medium">{sample.title}</p>
                <p className="mt-1 text-xs text-slate-500">人工选择 · {new Date(sample.selected_at).toLocaleString("zh-CN")}</p>
              </li>
            ))}
          </ul>
          {samples.length === 0 ? <p className="mt-4 text-slate-400">尚未选择样本</p> : null}
        </section>

        <section className="rounded-3xl border border-slate-800 bg-slate-900 p-6">
          <h2 className="text-xl font-semibold">已发布候选内容</h2>
          <ul className="mt-4 space-y-3">
            {candidates.map((candidate) => (
              <li className="flex items-center justify-between gap-4 rounded-xl bg-slate-950 p-4" key={candidate.content_id}>
                <div>
                  <p className="font-medium">{candidate.title}</p>
                  <p className="mt-1 text-xs text-slate-500">爆款与最近发布均需人工选择</p>
                </div>
                <button
                  className="rounded-lg bg-cyan-400 px-3 py-2 text-sm font-semibold text-slate-950 disabled:opacity-50"
                  disabled={candidate.selected || busy === candidate.content_id}
                  onClick={() => chooseSample(candidate)}
                  type="button"
                >
                  {candidate.selected ? "已选择" : "选择为风格样本"}
                </button>
              </li>
            ))}
          </ul>
        </section>
      </div>

      <section className="rounded-3xl border border-slate-800 bg-slate-900 p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold">提取结果与版本差异</h2>
            <p className="mt-1 text-sm text-slate-400">每次提取都会创建不可变新版本，确认后才参与生成。</p>
          </div>
          <button
            className="rounded-xl bg-fuchsia-400 px-4 py-2 font-semibold text-slate-950 disabled:opacity-50"
            disabled={busy === "extract" || samples.length === 0}
            onClick={extract}
            type="button"
          >
            重新提取风格档案
          </button>
        </div>

        {latestProfile ? (
          <div className="mt-5 space-y-4 rounded-2xl bg-slate-950 p-5">
            <div className="flex flex-wrap items-center gap-3">
              <strong>{latestProfile.status === "confirmed" ? "已确认" : "待确认"} · v{latestProfile.version}</strong>
              <span className="text-sm text-slate-400">
                {baseVersion ? `相对 v${baseVersion} 变化：${changedSections.map((section) => SECTION_LABELS[section] ?? section).join("、")}` : "首个版本"}
              </span>
            </div>
            <p>标题钩子：{stringValues(titleStyle.hooks).join("、") || "未识别"}</p>
            <p>文案语气：{stringValues(copyStyle.tones).join("、") || "未识别"}</p>
            <p>封面配色：{stringValues(coverStyle.colors).join("、") || "未识别"}</p>
            <p>禁止表达：{stringValues(prohibited.expressions).join("、") || "无"}</p>
            <ul className="text-sm text-slate-400">
              {latestProfile.sample_sources.map((source, index) => (
                <li key={String(source.content_id)}>来源 {index + 1} · {String(source.title)}</li>
              ))}
            </ul>
            {latestProfile.status === "pending_confirmation" ? (
              <button
                className="rounded-xl bg-emerald-400 px-4 py-2 font-semibold text-slate-950"
                disabled={busy === latestProfile.id}
                onClick={() => confirm(latestProfile)}
                type="button"
              >
                确认并启用 v{latestProfile.version}
              </button>
            ) : null}
          </div>
        ) : <p className="mt-5 text-slate-400">尚未提取风格档案</p>}
      </section>
    </section>
  );
}
