"use client";

import Link from "next/link";
import type { ReactElement } from "react";

import type {
  AgentAccount,
  AgentBriefingData,
} from "@/lib/agent-api";

import { useOptionalExperiencePreferences } from "@/components/workbench/experience-preferences-context";
import { Panel, StatusBadge } from "@/components/workbench/ui";


const platformLabel = {
  douyin: "抖音",
  xiaohongshu: "小红书",
} as const;

const preparationRoutes = {
  incomplete_data: { label: "去导入数据", suffix: "/imports" },
  import_waiting_confirmation: { label: "去确认导入", suffix: "/imports" },
  configuration_required: { label: "去检查模型配置", suffix: "/settings/models" },
} as const;

export function DailySuggestionCard({
  accounts,
  briefing,
  role,
  workspaceId,
  onDefer,
  onSuppress,
}: {
  accounts: AgentAccount[];
  briefing: AgentBriefingData;
  role: "admin" | "editor" | "viewer";
  workspaceId: string;
  onDefer: () => void;
  onSuppress: () => void;
}): ReactElement {
  const professional =
    useOptionalExperiencePreferences()?.copyMode === "professional";
  const suggestion = briefing.primary;
  const account = accounts.find(
    (item) => item.account_id === suggestion?.account_id,
  );
  const preparation = suggestion
    ? preparationRoutes[suggestion.kind as keyof typeof preparationRoutes]
    : undefined;
  const canEdit = role !== "viewer";

  return (
    <Panel
      description="系统每天只突出一件最值得先处理的事，你仍然决定是否执行。"
      title="今天建议先处理"
    >
      {!suggestion ? (
        <p className="text-sm text-[var(--text-secondary)]">
          当前没有可靠建议。先补充账号和发布后的数据，系统不会为了填满页面而猜测。
        </p>
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge tone="info">
              {platformLabel[suggestion.platform]}
            </StatusBadge>
            <span className="text-sm font-medium">
              {platformLabel[suggestion.platform]} · {account?.name ?? "账号"}
            </span>
          </div>
          <div>
            <h3 className="text-lg font-semibold">{suggestion.safe_title}</h3>
            <p className="mt-1 text-sm leading-6 text-[var(--text-secondary)]">
              {suggestion.safe_reason}
            </p>
          </div>
          <p className="text-sm text-[var(--text-secondary)]">
            有 {suggestion.evidence_refs.length} 条可核对依据
          </p>
          <p className="text-xs text-[var(--text-secondary)]">
            数据截止：{new Date(briefing.data_cutoff_at).toLocaleString("zh-CN")}
          </p>
          {professional ? (
            <dl className="rounded-lg bg-slate-50 p-3 text-xs text-[var(--text-secondary)]">
              <div>
                <dt className="inline">算法 / 工具目录：</dt>
                <dd className="inline">{briefing.algorithm_version} / {briefing.tool_catalog_version}</dd>
              </div>
              <div className="mt-1">
                <dt className="inline">Evidence IDs：</dt>
                <dd className="inline break-all">
                  {suggestion.evidence_refs.join("、") || "无"}
                </dd>
              </div>
            </dl>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Link
              className="rounded-lg bg-[var(--brand)] px-4 py-2 text-sm font-semibold text-white"
              href={preparation
                ? `/workspaces/${workspaceId}${preparation.suffix}`
                : "#agent-plan"}
            >
              {preparation?.label ?? "查看处理计划"}
            </Link>
            {canEdit ? (
              <>
                <button
                  className="rounded-lg border px-4 py-2 text-sm font-semibold"
                  onClick={onDefer}
                  type="button"
                >
                  今天稍后再看
                </button>
                <button
                  className="rounded-lg px-4 py-2 text-sm text-[var(--text-secondary)]"
                  onClick={onSuppress}
                  type="button"
                >
                  暂不建议此类事项
                </button>
              </>
            ) : null}
          </div>
        </div>
      )}
    </Panel>
  );
}
