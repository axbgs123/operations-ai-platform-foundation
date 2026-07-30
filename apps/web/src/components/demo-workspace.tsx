"use client";

import type { components } from "@operations-ai/shared-schemas";
import Link from "next/link";
import { useEffect, useState } from "react";

import { DemoBanner } from "@/components/demo-banner";
import { Panel, StatusBadge } from "@/components/workbench/ui";
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
      <main className="min-h-screen bg-[var(--canvas)] px-6 py-16 text-[var(--text-primary)]">
        <p>{error || "正在加载示例数据…"}</p>
      </main>
    );
  }
  const demo = workspace as DemoWorkspaceData & Record<string, Record<string, string | boolean | number>>;
  const closureCards: Array<[string, unknown]> = [
    ["已发布内容", demo.published_content?.title],
    ["正式确认数据快照", demo.confirmed_snapshot?.label],
    ["动态基准 / 图表", demo.benchmark?.label],
    ["Mock 分析", demo.analysis?.summary],
    ["建议", demo.suggestion?.text],
    ["风格样本", demo.style_sample?.label],
    ["已确认事实", demo.confirmed_fact?.value],
    ["合成风控知识", demo.risk_knowledge?.rule],
    ["生成草稿", demo.draft?.title],
  ];

  return (
    <main className="min-h-screen bg-[var(--canvas)] px-4 py-8 text-[var(--text-primary)] sm:px-6">
      <div className="mx-auto max-w-6xl space-y-8">
        <DemoBanner />
        <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
          <p className="text-sm font-medium text-blue-700">{workspace.label}</p>
          <h1 className="mt-2 text-3xl font-semibold">{workspace.name}</h1>
          <p className="mt-3 max-w-2xl text-[var(--text-secondary)]">
            在不注册、不接入真实账号的情况下，先了解数据复盘和内容生成的工作方式。
          </p>
          </div>
          <Link
            className="rounded-lg bg-[var(--brand)] px-4 py-2 text-center text-sm font-semibold text-white"
            href="/enter"
          >
            进入私有工作区
          </Link>
        </header>

        <section className="grid gap-5 md:grid-cols-2">
          {workspace.accounts.map((account) => (
            <article key={account.id} className="rounded-xl border bg-white p-6">
              <StatusBadge tone="info">示例数据</StatusBadge>
              <h2 className="mt-4 text-xl font-semibold">
                {account.platform === "douyin" ? "抖音" : "小红书"} · {account.name}
              </h2>
              <p className="mt-2 text-sm text-[var(--text-secondary)]">{account.posts.length} 条合成作品记录</p>
            </article>
          ))}
        </section>

        <section aria-label="示例运营闭环" className="grid gap-4 md:grid-cols-3">
          {closureCards.map(([title, detail]) => (
            <article key={title} className="rounded-xl border bg-white p-5">
              <h2 className="font-semibold">{title}</h2>
              <p className="mt-2 text-sm text-[var(--text-secondary)]">{detail === undefined ? "示例数据加载中" : String(detail)}</p>
            </article>
          ))}
        </section>

        <Panel
          description="每个匿名会话 3 次、每个 IP 每日 5 次；仅调用本地受限 Mock，不产生费用。"
          title="试用标题生成"
        >
          <button
            className="rounded-lg bg-[var(--brand)] px-5 py-3 font-semibold text-white disabled:opacity-50"
            disabled={pending}
            onClick={handleGenerate}
            type="button"
          >
            {pending ? "正在生成…" : "生成 Mock 标题"}
          </button>
          {generation ? (
            <div className="mt-5 rounded-xl bg-slate-50 p-5">
              <strong className="text-blue-800">Mock 输出</strong>
              <p className="mt-2">{generation.content}</p>
              <p className="mt-2 text-sm text-[var(--text-secondary)]">本会话剩余 {generation.remaining} 次</p>
            </div>
          ) : null}
          {error ? <p className="mt-4 text-sm text-red-700">{error}</p> : null}
        </Panel>
      </div>
    </main>
  );
}
