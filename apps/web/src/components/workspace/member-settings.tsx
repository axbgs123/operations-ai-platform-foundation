"use client";

import { FormEvent, useState } from "react";

import { createMemberCode } from "@/lib/workspace-api";


export function MemberSettings({ workspaceId }: { workspaceId: string }) {
  const [code, setCode] = useState("");
  const [error, setError] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const role = String(form.get("role")) as "admin" | "editor" | "viewer";
    const csrf = sessionStorage.getItem("workspace_csrf") ?? "";
    try {
      const result = await createMemberCode(workspaceId, role, csrf);
      setCode(result.code);
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "生成失败");
    }
  }

  return (
    <section className="rounded-3xl border border-slate-800 bg-slate-900 p-8">
      <h1 className="text-3xl font-semibold">成员与邀请码</h1>
      <p className="mt-3 text-slate-400">
        坚持一人一码、一种角色；成员离开后可单独撤销，不影响其他人。
      </p>
      <form className="mt-8 flex flex-col gap-4 sm:flex-row" onSubmit={handleSubmit}>
        <label className="flex-1 text-sm font-medium">
          成员角色
          <select
            className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3"
            defaultValue="viewer"
            name="role"
          >
            <option value="viewer">查看者</option>
            <option value="editor">编辑者</option>
            <option value="admin">管理员</option>
          </select>
        </label>
        <button
          className="self-end rounded-xl bg-cyan-400 px-5 py-3 font-semibold text-slate-950"
          type="submit"
        >
          生成独立邀请码
        </button>
      </form>
      {code ? (
        <output className="mt-6 block break-all rounded-xl bg-slate-950 p-4 font-mono text-sm text-cyan-300">
          {code}
        </output>
      ) : null}
      {error ? <p className="mt-4 text-sm text-rose-400">{error}</p> : null}
    </section>
  );
}
