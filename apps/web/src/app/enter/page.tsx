"use client";

import { FormEvent, useState } from "react";

import { enterWorkspace } from "@/lib/workspace-api";


export default function EnterPage() {
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setPending(true);
    setError("");
    try {
      const session = await enterWorkspace(
        String(form.get("code") ?? ""),
        String(form.get("displayName") ?? ""),
      );
      sessionStorage.setItem("workspace_csrf", session.csrf_token);
      window.location.assign(
        `/workspaces/${session.workspace_id}/settings/members`,
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "进入失败");
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="min-h-screen bg-slate-950 px-6 py-16 text-slate-100">
      <section className="mx-auto max-w-md rounded-3xl border border-slate-800 bg-slate-900 p-8 shadow-2xl">
        <p className="mb-3 text-sm font-medium text-cyan-400">安全工作区入口</p>
        <h1 className="text-3xl font-semibold">使用邀请码进入工作区</h1>
        <p className="mt-3 text-sm leading-6 text-slate-400">
          邀请码与成员身份一一绑定，管理员可随时撤销。
        </p>
        <form className="mt-8 space-y-5" onSubmit={handleSubmit}>
          <label className="block text-sm font-medium">
            邀请码
            <input
              className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 outline-none focus:border-cyan-400"
              name="code"
              required
            />
          </label>
          <label className="block text-sm font-medium">
            显示名称
            <input
              className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 outline-none focus:border-cyan-400"
              name="displayName"
              required
            />
          </label>
          {error ? <p className="text-sm text-rose-400">{error}</p> : null}
          <button
            className="w-full rounded-xl bg-cyan-400 px-4 py-3 font-semibold text-slate-950 disabled:opacity-50"
            disabled={pending}
            type="submit"
          >
            {pending ? "正在验证…" : "进入工作区"}
          </button>
        </form>
      </section>
    </main>
  );
}
