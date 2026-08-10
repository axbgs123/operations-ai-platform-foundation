"use client";

import Link from "next/link";
import type { ReactElement } from "react";

import type {
  WorkbenchAccount,
  WorkbenchPlatform,
  WorkbenchScope,
} from "./scope-query";


export function ScopeFilters({
  accounts,
  scope,
  onScopeChange,
  createAccountHref,
}: {
  accounts: readonly WorkbenchAccount[];
  scope: WorkbenchScope;
  onScopeChange: (scope: WorkbenchScope) => void;
  createAccountHref?: string;
}): ReactElement {
  const compatibleAccounts = scope.platform
    ? accounts.filter((account) => account.platform === scope.platform)
    : accounts;

  function changePlatform(value: string) {
    const platform = (value || undefined) as WorkbenchPlatform | undefined;
    const selectedAccount = accounts.find(
      (account) => account.account_id === scope.accountId,
    );
    onScopeChange({
      ...(platform ? { platform } : {}),
      ...(platform && selectedAccount?.platform === platform
        ? { accountId: selectedAccount.account_id }
        : {}),
    });
  }

  function changeAccount(value: string) {
    const account = accounts.find((item) => item.account_id === value);
    onScopeChange(
      account
        ? { platform: account.platform, accountId: account.account_id }
        : scope.platform
          ? { platform: scope.platform }
          : {},
    );
  }

  return (
    <div aria-label="数据范围" className="flex min-w-0 gap-2" role="group">
      <label className="min-w-0">
        <span className="sr-only">平台范围</span>
        <select
          aria-label="平台范围"
          className="h-10 max-w-36 rounded-lg border bg-white px-3 text-sm text-[var(--text-primary)]"
          data-workbench-control="select"
          onChange={(event) => changePlatform(event.target.value)}
          value={scope.platform ?? ""}
        >
          <option value="">全部平台</option>
          <option value="douyin">抖音</option>
          <option value="xiaohongshu">小红书</option>
        </select>
      </label>
      <label className="min-w-0">
        <span className="sr-only">账号范围</span>
        <select
          aria-label="账号范围"
          className="h-10 max-w-44 rounded-lg border bg-white px-3 text-sm text-[var(--text-primary)]"
          data-workbench-control="select"
          onChange={(event) => changeAccount(event.target.value)}
          value={scope.accountId ?? ""}
        >
          <option value="">全部账号</option>
          {compatibleAccounts.map((account) => (
            <option key={account.account_id} value={account.account_id}>
              {account.name}
            </option>
          ))}
        </select>
      </label>
      {createAccountHref ? (
        <Link
          aria-label="创建账号"
          className="inline-flex h-10 shrink-0 items-center rounded-lg border border-violet-200 bg-violet-50 px-3 text-sm font-semibold text-[var(--brand)] hover:bg-violet-100"
          href={createAccountHref}
        >
          <span aria-hidden="true">＋</span>
          <span className="ml-1">创建账号</span>
        </Link>
      ) : null}
    </div>
  );
}
