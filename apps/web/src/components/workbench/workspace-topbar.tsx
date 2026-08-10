"use client";

import Link from "next/link";
import { useEffect, useState, type ReactElement } from "react";

import { loadAgentConfirmations } from "@/lib/agent-api";
import type { WorkbenchContext } from "@/lib/workbench-api";

import { Breadcrumbs } from "./breadcrumbs";
import { ExperienceControls } from "./experience-controls";
import { ScopeFilters } from "./scope-filters";
import type { WorkbenchScope } from "./scope-query";


const ROLE_LABELS = {
  admin: "管理员",
  editor: "编辑者",
  viewer: "查看者",
} as const;

export function WorkspaceTopbar({
  context,
  pathname,
  scope,
  onScopeChange,
  isMobile,
  onOpenNavigation,
  navigationTriggerRef,
  loadConfirmations = loadAgentConfirmations,
}: {
  context: WorkbenchContext;
  pathname: string;
  scope: WorkbenchScope;
  onScopeChange: (scope: WorkbenchScope) => void;
  isMobile: boolean;
  onOpenNavigation: () => void;
  navigationTriggerRef: React.RefObject<HTMLButtonElement | null>;
  loadConfirmations?: typeof loadAgentConfirmations;
}): ReactElement {
  const [pendingConfirmationCount, setPendingConfirmationCount] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    loadConfirmations(context.workspace_id, controller.signal)
      .then(({ items }) => setPendingConfirmationCount(
        items.filter((item) => item.status === "pending").length,
      ))
      .catch(() => {
        if (!controller.signal.aborted) setPendingConfirmationCount(0);
      });
    return () => controller.abort();
  }, [context.member_id, context.workspace_id, loadConfirmations]);
  return (
    <header className="flex min-h-14 flex-wrap items-center gap-3 border-b bg-white px-4 py-2 sm:px-5">
      {isMobile ? (
        <button
          aria-label="打开主导航"
          className="inline-flex h-10 w-10 items-center justify-center rounded-lg border bg-white text-lg"
          onClick={onOpenNavigation}
          ref={navigationTriggerRef}
          type="button"
        >
          ☰
        </button>
      ) : null}
      <div className="min-w-48 flex-1">
        <Breadcrumbs
          pathname={pathname}
          role={context.role}
          scope={scope}
          workspaceId={context.workspace_id}
          workspaceName={context.workspace_name}
        />
      </div>
      <ScopeFilters
        accounts={context.accounts}
        createAccountHref={
          context.role === "viewer"
            ? undefined
            : `/workspaces/${context.workspace_id}/accounts?action=create`
        }
        onScopeChange={onScopeChange}
        scope={scope}
      />
      {context.failed_task_count > 0 ? (
        <span aria-live="polite" role="status">
          <Link
            className="block rounded-lg bg-red-50 px-3 py-2 text-sm font-semibold text-red-800"
            href={`/workspaces/${context.workspace_id}/settings/jobs`}
          >
            {context.failed_task_count} 个失败任务
          </Link>
        </span>
      ) : null}
      {pendingConfirmationCount > 0 ? (
        <span aria-live="polite" role="status">
          <Link
            className="block rounded-lg bg-amber-50 px-3 py-2 text-sm font-semibold text-amber-900"
            href={`/workspaces/${context.workspace_id}/agent?view=confirmations`}
          >
            {pendingConfirmationCount} 个操作待确认
          </Link>
        </span>
      ) : null}
      <ExperienceControls compact={isMobile} />
      <Link
        className="rounded-lg px-2 py-2 text-sm text-[var(--text-secondary)] hover:bg-slate-100"
        href="/#help"
      >
        帮助
      </Link>
      <div
        aria-label="当前成员"
        className="rounded-lg border bg-white px-3 py-1.5 text-right"
        role="group"
      >
        <p className="text-sm font-medium text-[var(--text-primary)]">
          {context.member_display_name}
        </p>
        <p className="text-xs text-[var(--text-secondary)]">
          {ROLE_LABELS[context.role]}
        </p>
      </div>
    </header>
  );
}
