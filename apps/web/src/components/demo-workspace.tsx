"use client";

import type { components } from "@operations-ai/shared-schemas";
import { useEffect, useState } from "react";

import { DemoBanner } from "@/components/demo-banner";
import { createDemoSession, generateDemoTitle, loadDemoWorkspace } from "@/lib/demo-api";

export type DemoWorkspaceData = components["schemas"]["DemoWorkspaceRead"];

export function DemoWorkspace({
  initialWorkspace,
}: {
  initialWorkspace?: DemoWorkspaceData;
}) {
  const [workspace, setWorkspace] = useState(initialWorkspace);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [generation, setGeneration] = useState<{
    content: string;
    remaining: number;
  }>();
  const [sessionStarted, setSessionStarted] = useState(false);

  useEffect(() => {
    if (initialWorkspace) return;
    loadDemoWorkspace().then(setWorkspace).catch((caught) => {
      setError(caught instanceof Error ? caught.message : "公开体验区暂时不可用");
    });
  }, [initialWorkspace]);

  async function handleGenerate() {
    setPending(true);
    setError("");
    try {
      if (!sessionStarted) {
        await createDemoSession();
        setSessionStarted(true);
      }
      const result = await generateDemoTitle("为通勤穿搭账号生成一个真实、不夸大的标题");
      setGeneration({ content: result.content, remaining: result.session_remaining });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "生成失败");
    } finally {
      setPending(false);
    }
  }

  if (!workspace) {
    return (
      <main className="min-h-screen bg-slate-950 px-6 py-16 text-slate-100">
        <p>{error || "正在加载示例数据…"}</p>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-slate-950 px-6 py-10 text-slate-100">
      <div className="mx-auto max-w-6xl space-y-8">
        <DemoBanner />
        <header>
          <p className="text-sm font-medium text-cyan-400">{workspace.label}</p>
          <h1 className="mt-2 text-4xl font-semibold">{workspace.name}</h1>
          <p className="mt-3 max-w-2xl text-slate-400">
            在不注册、不接入真实账号的情况下，先了解数据复盘和内容生成的工作方式。
          </p>
        </header>

        <section className="grid gap-5 md:grid-cols-2">
          {workspace.accounts.map((account) => (
            <article key={account.id} className="rounded-3xl border border-slate-800 bg-slate-900 p-6">
              <span className="rounded-full bg-cyan-400/10 px-3 py-1 text-xs text-cyan-300">
                示例数据
              </span>
              <h2 className="mt-4 text-xl font-semibold">
                {account.platform === "douyin" ? "抖音" : "小红书"} · {account.name}
              </h2>
              <p className="mt-2 text-sm text-slate-400">{account.posts.length} 条合成作品记录</p>
            </article>
          ))}
        </section>

        <section className="rounded-3xl border border-slate-800 bg-slate-900 p-6">
          <h2 className="text-xl font-semibold">试用标题生成</h2>
          <p className="mt-2 text-sm text-slate-400">每个匿名会话 3 次、每个 IP 每日 5 次。</p>
          <button
            className="mt-5 rounded-xl bg-cyan-400 px-5 py-3 font-semibold text-slate-950 disabled:opacity-50"
            disabled={pending}
            onClick={handleGenerate}
            type="button"
          >
            {pending ? "正在生成…" : "生成 Mock 标题"}
          </button>
          {generation ? (
            <div className="mt-5 rounded-2xl bg-slate-950 p-5">
              <strong className="text-cyan-300">Mock 输出</strong>
              <p className="mt-2">{generation.content}</p>
              <p className="mt-2 text-sm text-slate-500">本会话剩余 {generation.remaining} 次</p>
            </div>
          ) : null}
          {error ? <p className="mt-4 text-sm text-rose-400">{error}</p> : null}
        </section>
      </div>
    </main>
  );
}
