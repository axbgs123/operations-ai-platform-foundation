"use client";

import { FormEvent, useState } from "react";

import { createContent } from "@/lib/content-api";


export function NewContentForm({ workspaceId, accountId, platform }: { workspaceId: string; accountId: string; platform: "douyin" | "xiaohongshu" }) {
  const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const content = await createContent({
        workspace_id: workspaceId,
        account_id: accountId,
        platform,
        title: String(form.get("title") ?? ""),
        body: String(form.get("body") ?? ""),
        work_url: String(form.get("workUrl") ?? "") || undefined,
      }, sessionStorage.getItem("workspace_csrf") ?? "");
      window.location.assign(`/workspaces/${workspaceId}/contents/${content.id}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "创建失败");
    }
  }
  return <form className="mx-auto max-w-2xl space-y-5 rounded-3xl border border-slate-800 bg-slate-900 p-7" onSubmit={submit}>
    <h1 className="text-3xl font-semibold">新建单条作品</h1>
    <label className="block">标题<input className="mt-2 w-full rounded-xl bg-slate-950 px-4 py-3" name="title" required /></label>
    <label className="block">文案<textarea className="mt-2 min-h-48 w-full rounded-xl bg-slate-950 px-4 py-3" name="body" /></label>
    <label className="block">作品链接（可选）<input className="mt-2 w-full rounded-xl bg-slate-950 px-4 py-3" name="workUrl" type="url" /></label>
    {error ? <p className="text-rose-400">{error}</p> : null}
    <button className="rounded-xl bg-cyan-400 px-5 py-3 font-semibold text-slate-950" type="submit">创建作品</button>
  </form>;
}
