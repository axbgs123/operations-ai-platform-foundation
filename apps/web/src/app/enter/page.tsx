"use client";

import { FormEvent, useRef, useState } from "react";

import {
  enterWorkspace,
  onboardWorkspaceOwner,
} from "@/lib/workspace-api";

type EntryMode = "create" | "join";

export default function EnterPage() {
  const [mode, setMode] = useState<EntryMode>("create");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const pendingRef = useRef(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pendingRef.current) {
      return;
    }
    const submittingMode = mode;
    const form = new FormData(event.currentTarget);
    pendingRef.current = true;
    setPending(true);
    setError("");
    try {
      const displayName = String(form.get("displayName") ?? "");
      const session =
        submittingMode === "create"
          ? await onboardWorkspaceOwner(
              String(form.get("workspaceName") ?? ""),
              displayName,
            )
          : await enterWorkspace(String(form.get("code") ?? ""), displayName);
      sessionStorage.setItem("workspace_csrf", session.csrf_token);
      window.location.assign(`/workspaces/${session.workspace_id}`);
    } catch {
      setError(
        submittingMode === "create"
          ? "创建失败，请稍后重试"
          : "加入失败，请稍后重试",
      );
    } finally {
      pendingRef.current = false;
      setPending(false);
    }
  }

  return (
    <main className="min-h-screen bg-[var(--canvas)] px-4 py-10 text-[var(--text-primary)] sm:px-6 sm:py-16">
      <section
        aria-labelledby="workspace-entry-title"
        className="mx-auto max-w-lg rounded-3xl border border-[var(--border)] bg-[var(--surface)] p-6 shadow-sm sm:p-8"
      >
        <p className="mb-3 text-sm font-medium text-[var(--brand)]">
          安全工作区入口
        </p>
        <h1
          className="text-3xl font-semibold"
          id="workspace-entry-title"
        >
          进入你的运营工作区
        </h1>
        <p className="mt-3 text-sm leading-6 text-[var(--text-secondary)]">
          创建新团队，或使用管理员提供的独立邀请码加入已有团队。
        </p>
        <div
          aria-label="进入方式"
          className="mt-8 grid grid-cols-1 gap-3 sm:grid-cols-2"
          role="group"
        >
          {(["create", "join"] as const).map((entryMode) => {
            const active = mode === entryMode;
            const label = entryMode === "create" ? "创建团队" : "加入团队";
            return (
              <button
                aria-pressed={active}
                className={`rounded-xl border px-4 py-3 text-left font-semibold disabled:cursor-not-allowed disabled:opacity-50 ${
                  active
                    ? "border-[var(--brand)] bg-[var(--brand)] text-white"
                    : "border-[var(--border)] bg-[var(--surface)] text-[var(--text-primary)]"
                }`}
                disabled={pending}
                key={entryMode}
                onClick={() => {
                  setMode(entryMode);
                  setError("");
                }}
                type="button"
              >
                {label}
              </button>
            );
          })}
        </div>
        <form
          aria-label={mode === "create" ? "创建团队表单" : "加入团队表单"}
          className="mt-8 space-y-5"
          onSubmit={handleSubmit}
        >
          {mode === "create" ? (
            <label className="block text-sm font-medium">
              团队名称
              <input
                autoComplete="organization"
                className="mt-2 w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-[var(--text-primary)] focus:border-[var(--brand)]"
                name="workspaceName"
                required
              />
            </label>
          ) : (
            <label className="block text-sm font-medium">
              邀请码
              <input
                autoComplete="off"
                className="mt-2 w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-[var(--text-primary)] focus:border-[var(--brand)]"
                name="code"
                required
              />
            </label>
          )}
          <label className="block text-sm font-medium">
            我的名称
            <input
              autoComplete="name"
              className="mt-2 w-full rounded-xl border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-[var(--text-primary)] focus:border-[var(--brand)]"
              name="displayName"
              required
            />
          </label>
          {error ? (
            <p
              aria-label={error}
              className="text-sm text-[var(--danger)]"
              role="alert"
            >
              {error}
            </p>
          ) : null}
          <button
            className="w-full rounded-xl bg-[var(--brand)] px-4 py-3 font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
            disabled={pending}
            type="submit"
          >
            {pending
              ? mode === "create"
                ? "正在创建…"
                : "正在加入…"
              : mode === "create"
                ? "创建团队并进入"
                : "加入团队"}
          </button>
        </form>
        <div className="mt-6 space-y-2 border-t border-[var(--border)] pt-5 text-sm leading-6 text-[var(--text-secondary)]">
          <p>创建团队不需要邀请码，创建者将成为首位管理员。</p>
          <p>
            团队名称和我的名称只是工作区中的显示信息，不是账号或密码。
          </p>
          <p>
            当前会话只保存在这台浏览器中；换浏览器或换电脑后，需要另一个管理员邀请码重新加入。
          </p>
        </div>
      </section>
    </main>
  );
}
