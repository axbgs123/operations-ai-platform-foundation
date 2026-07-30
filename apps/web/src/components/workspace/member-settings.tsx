"use client";

import { FormEvent, useEffect, useState } from "react";

import { useWorkbenchShellContext } from "@/components/workbench/workspace-shell";
import {
  createMemberCode,
  listWorkspaceMembers,
  revokeWorkspaceMember,
  updateWorkspaceMemberRole,
  type WorkspaceMemberManagement,
} from "@/lib/workspace-api";

type Role = "admin" | "editor" | "viewer";

export function MemberSettings({
  workspaceId,
  role: suppliedRole,
  fixture,
}: {
  workspaceId: string;
  role?: Role;
  fixture?: WorkspaceMemberManagement[];
}) {
  const context = useWorkbenchShellContext();
  const role = suppliedRole ?? context?.role ?? "viewer";
  const canManage = role === "admin";
  const [code, setCode] = useState("");
  const [members, setMembers] = useState(fixture ?? []);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!canManage || fixture) return;
    let active = true;
    listWorkspaceMembers(workspaceId)
      .then((items) => {
        if (active) setMembers(items);
      })
      .catch((caught: unknown) => {
        if (active) {
          setError(caught instanceof Error ? caught.message : "成员列表加载失败");
        }
      });
    return () => {
      active = false;
    };
  }, [canManage, fixture, workspaceId]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const role = String(form.get("role")) as "admin" | "editor" | "viewer";
    try {
      const result = await createMemberCode(
        workspaceId,
        role,
        sessionStorage.getItem("workspace_csrf") ?? "",
      );
      setCode(result.code);
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "生成失败");
    }
  }

  async function changeRole(
    member: WorkspaceMemberManagement,
    nextRole: "admin" | "editor" | "viewer",
  ) {
    setError("");
    try {
      const updated = await updateWorkspaceMemberRole(
        workspaceId,
        member.id,
        nextRole,
        sessionStorage.getItem("workspace_csrf") ?? "",
      );
      setMembers((current) =>
        current.map((item) =>
          item.id === updated.id ? { ...item, role: updated.role } : item,
        ),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "角色调整失败");
    }
  }

  async function revoke(member: WorkspaceMemberManagement) {
    setError("");
    try {
      const updated = await revokeWorkspaceMember(
        workspaceId,
        member.id,
        sessionStorage.getItem("workspace_csrf") ?? "",
      );
      setMembers((current) =>
        current.map((item) =>
          item.id === updated.id
            ? { ...item, status: "revoked", invite_status: "revoked" }
            : item,
        ),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "撤销成员失败");
    }
  }

  return (
    <section className="rounded-xl border bg-white p-8">
      <h1 className="text-3xl font-semibold">成员与邀请码</h1>
      <p className="mt-3 text-[var(--text-secondary)]">
        坚持一人一码、一种角色；成员离开后可单独撤销，不影响其他人。
      </p>
      <p className="mt-2 text-sm text-[var(--text-secondary)]">
        邀请码只在新建时显示一次，无法找回原邀请码；页面不会写入 URL 或浏览器持久化存储。
      </p>
      {canManage ? (
        <form className="mt-8 flex flex-col gap-4 sm:flex-row" onSubmit={handleSubmit}>
          <label className="flex-1 text-sm font-medium">
            成员角色
            <select
              className="mt-2 w-full rounded-xl border bg-white px-4 py-3"
              defaultValue="viewer"
              name="role"
            >
              <option value="viewer">查看者</option>
              <option value="editor">编辑者</option>
              <option value="admin">管理员</option>
            </select>
          </label>
          <button
            className="self-end rounded-xl bg-[var(--brand)] px-5 py-3 font-semibold text-white"
            type="submit"
          >
            生成独立邀请码
          </button>
        </form>
      ) : (
        <p className="mt-6 rounded-lg bg-slate-50 p-4 text-sm">
          当前角色不可管理成员或邀请码。
        </p>
      )}
      {code ? (
        <output className="mt-6 block break-all rounded-xl bg-slate-50 p-4 font-mono text-sm text-blue-800">
          {code}
        </output>
      ) : null}
      {error ? <p className="mt-4 text-sm text-red-800" role="alert">{error}</p> : null}
      {canManage ? (
        <div className="mt-8 space-y-3" aria-label="成员列表">
          {members.length === 0 ? (
            <p className="text-sm text-[var(--text-secondary)]" role="status">
              正在加载成员，或当前没有可管理成员。
            </p>
          ) : null}
          {members.map((member) => {
            const isCurrent = member.id === context?.member_id;
            return (
              <article className="rounded-xl border p-4" key={member.id}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <strong>{member.display_name}</strong>
                    <p className="mt-1 text-sm text-[var(--text-secondary)]">
                      状态：{member.status === "active" ? "有效" : "已撤销"} ·
                      邀请码：{member.invite_status === "redeemed" ? "已兑换" : "已撤销"}
                    </p>
                    <p className="mt-1 text-sm text-[var(--text-secondary)]">
                      最后访问：{member.last_access_status === "not_recorded" ? "当前认证合同未记录" : member.last_access_at}
                    </p>
                  </div>
                  <span className="rounded-full border bg-slate-50 px-3 py-1 text-xs font-semibold">
                    {member.role}
                  </span>
                </div>
                {member.status === "active" && !isCurrent ? (
                  <div className="mt-4 flex flex-wrap gap-2">
                    <label className="text-sm">
                      调整角色
                      <select
                        aria-label={`调整 ${member.display_name} 的角色`}
                        className="ml-2 rounded-lg border px-2 py-1"
                        onChange={(event) =>
                          void changeRole(
                            member,
                            event.target.value as "admin" | "editor" | "viewer",
                          )
                        }
                        value={member.role === "demo" ? "viewer" : member.role}
                      >
                        <option value="admin">管理员</option>
                        <option value="editor">编辑者</option>
                        <option value="viewer">查看者</option>
                      </select>
                    </label>
                    <button
                      className="rounded-lg border border-red-700 px-3 py-1 text-sm text-red-800"
                      onClick={() => void revoke(member)}
                      type="button"
                    >
                      撤销 {member.display_name}
                    </button>
                  </div>
                ) : null}
              </article>
            );
          })}
        </div>
      ) : null}
    </section>
  );
}
