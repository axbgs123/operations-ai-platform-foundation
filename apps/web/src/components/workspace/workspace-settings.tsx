"use client";

import Link from "next/link";

import { GuidedPageHeader } from "@/components/workbench/guided-page-header";
import { useExperiencePreferences } from "@/components/workbench/experience-preferences-context";
import { Panel, StatusBadge } from "@/components/workbench/ui";
import { useWorkbenchShellContext } from "@/components/workbench/workspace-shell";

import { SettingsNav } from "./settings-nav";

type Role = "admin" | "editor" | "viewer";

export function WorkspaceSettings({
  workspaceId,
  role: suppliedRole,
}: {
  workspaceId: string;
  role?: Role;
}) {
  const context = useWorkbenchShellContext();
  const { copyMode } = useExperiencePreferences();
  const accounts = context?.accounts ?? [];
  const role = suppliedRole ?? context?.role;

  return (
    <div className="space-y-6">
      <GuidedPageHeader pageId="settings" />
      <SettingsNav workspaceId={workspaceId} />
      <Panel title="工作区概览">
        <dl className="grid gap-3 text-sm sm:grid-cols-3">
          <div><dt>团队名称</dt><dd>{context?.workspace_name ?? "正在加载"}</dd></div>
          <div><dt>我的权限</dt><dd>{context?.role ?? "正在加载"}</dd></div>
          <div><dt>平台账号</dt><dd>{accounts.length} 个</dd></div>
          <div><dt>运行状态</dt><dd>{context?.failed_task_count ? `${context.failed_task_count} 个任务需要重试` : "运行正常"}</dd></div>
          <div><dt>数据范围</dt><dd>仅当前团队可见</dd></div>
          <div><dt>运行版本</dt><dd>{copyMode === "simple" ? "轻量工作台" : "Lite workbench"}</dd></div>
        </dl>
      </Panel>
      <section className="grid gap-4 lg:grid-cols-2">
        <Panel title="成员与邀请码">
          <p className="text-sm text-[var(--text-secondary)]">
            管理员可以邀请编辑者或查看者加入团队。每个邀请码只给一个人使用。
          </p>
          {role === "viewer" ? (
            <p className="mt-4 text-sm font-semibold text-[var(--text-secondary)]">当前为只读权限</p>
          ) : (
            <Link className="mt-4 inline-block text-sm font-semibold text-blue-700" href={`/workspaces/${workspaceId}/settings/members`}>
              管理成员和邀请码
            </Link>
          )}
        </Panel>
        <Panel title="平台账号">
          <div className="space-y-2">
            {accounts.length === 0 ? <p className="text-sm text-[var(--text-secondary)]">还没有添加抖音或小红书账号。</p> : null}
            {accounts.map((account) => (
              <p className="rounded-lg bg-slate-50 p-3 text-sm" key={account.account_id}>
                <StatusBadge tone="info">{account.platform === "douyin" ? "抖音" : "小红书"}</StatusBadge>
                <span className="ml-2">{account.name}</span>
              </p>
            ))}
          </div>
          <div className="mt-4 flex flex-wrap gap-3">
            <Link className="text-sm font-semibold text-blue-700" href={`/workspaces/${workspaceId}/accounts`}>
              查看平台账号
            </Link>
            {role === "admin" ? (
              <Link className="text-sm font-semibold text-[var(--brand)]" href={`/workspaces/${workspaceId}/accounts?action=create`}>
                创建平台账号
              </Link>
            ) : null}
          </div>
        </Panel>
      </section>
      <Panel title="AI 模型连接">
        <div className="flex flex-wrap gap-2">
          <StatusBadge tone="info">使用自己的 API Key</StatusBadge>
          <StatusBadge tone="neutral">密钥保存后不再显示</StatusBadge>
          <StatusBadge tone="warning">调用费用由模型服务商收取</StatusBadge>
        </div>
        <p className="mt-3 text-sm text-[var(--text-secondary)]">
          连接模型后可用于分析、生成和运营智能体。演示模式不会调用真实模型。
        </p>
        {role === "viewer" ? (
          <p className="mt-4 text-sm font-semibold text-[var(--text-secondary)]">联系管理员配置模型</p>
        ) : (
          <Link className="mt-4 inline-block text-sm font-semibold text-blue-700" href={`/workspaces/${workspaceId}/settings/models`}>
            打开模型连接
          </Link>
        )}
      </Panel>
    </div>
  );
}
