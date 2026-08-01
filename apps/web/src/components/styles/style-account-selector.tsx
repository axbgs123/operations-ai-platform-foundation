"use client";

import Link from "next/link";
import type { ReactElement } from "react";

import { GuidedPageHeader } from "@/components/workbench/guided-page-header";
import type { WorkbenchAccount } from "@/components/workbench/scope-query";
import { EmptyState, StatusBadge } from "@/components/workbench/ui";
import { useWorkbenchShellContext } from "@/components/workbench/workspace-shell";

const styleBoundary = {
  simple: "账号风格用于保持表达稳定；优秀内容结构只是参考，不会自动变成账号风格。",
  professional: "账号 Style Profile 与已确认 Viral Reference 保持独立版本和引用边界。",
};

const platformLabel = {
  douyin: "抖音",
  xiaohongshu: "小红书",
} as const;

export function StyleAccountSelector({
  accounts,
  workspaceId,
}: {
  accounts: WorkbenchAccount[];
  workspaceId: string;
}): ReactElement {
  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <GuidedPageHeader context={styleBoundary} pageId="styles" />
      <div className="rounded-xl border bg-white p-4 text-sm text-[var(--text-secondary)]">
        <p>风格档案始终固定到单个平台账号，不提供全部账号合并视图。</p>
        <p className="mt-1">优秀内容结构不会自动变成账号风格。</p>
      </div>
      {accounts.length === 0 ? (
        <EmptyState
          description="先在工作区设置中创建抖音或小红书账号，再人工选择已发布内容作为风格样本。"
          title="还没有可维护的账号"
        />
      ) : (
        <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {accounts.map((account) => {
            const query = new URLSearchParams({
              platform: account.platform,
              account: account.account_id,
            });
            return (
              <li className="rounded-xl border bg-white p-5" key={account.account_id}>
                <StatusBadge tone={account.platform === "douyin" ? "info" : "warning"}>
                  {platformLabel[account.platform]}
                </StatusBadge>
                <h2 className="mt-3 text-lg font-semibold">{account.name}</h2>
                <p className="mt-2 text-sm text-[var(--text-secondary)]">
                  当前版本：进入账号查看
                </p>
                <p className="mt-1 text-sm text-[var(--text-secondary)]">
                  最近更新时间：进入账号查看
                </p>
                <Link
                  className="mt-4 inline-flex rounded-lg bg-[var(--brand)] px-4 py-2 text-sm font-semibold text-white"
                  href={`/workspaces/${workspaceId}/styles/${account.account_id}?${query}`}
                >
                  查看{account.name}风格
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

export function StyleAccountSelectorPage({
  workspaceId,
}: {
  workspaceId: string;
}): ReactElement {
  const context = useWorkbenchShellContext();
  if (!context) {
    return (
      <EmptyState
        description="工作区范围尚未加载，请稍后重试。"
        title="无法读取账号范围"
      />
    );
  }
  return (
    <StyleAccountSelector
      accounts={context.accounts}
      workspaceId={workspaceId}
    />
  );
}
