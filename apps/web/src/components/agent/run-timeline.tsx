"use client";

import type { ReactElement } from "react";

import type { AgentRunData } from "@/lib/agent-api";

import { useOptionalExperiencePreferences } from "@/components/workbench/experience-preferences-context";
import { EmptyState, StatusBadge } from "@/components/workbench/ui";


const toolLabels: Record<string, string> = {
  read_account_state: "查看账号状态",
  run_content_analysis: "分析内容表现",
  read_confirmed_facts: "核对事实资料",
  read_account_style: "读取账号风格",
  read_confirmed_viral_assets: "读取优秀内容参考",
  generate_optimization_draft: "正在生成优化草稿",
  scan_optimization_draft: "检查草稿风险",
  save_agent_summary: "保存执行摘要",
  create_agent_export: "创建执行报告",
};

const statusLabels = {
  pending: "等待开始",
  running: "处理中",
  awaiting_action_confirmation: "等待你确认",
  succeeded: "已完成",
  rejected: "已拒绝",
  cancelled: "已取消",
  failed: "处理失败",
  compensation_required: "需要安全清理",
  provider_outcome_unknown: "供应商结果待核对",
} as const;

export function agentToolLabel(toolName: string): string {
  return toolLabels[toolName] ?? "执行受控步骤";
}

export function RunTimeline({
  run,
}: {
  run?: AgentRunData;
}): ReactElement {
  const professional =
    useOptionalExperiencePreferences()?.copyMode === "professional";
  if (!run) {
    return (
      <EmptyState
        description="批准处理计划后，执行步骤和状态会保存在服务器中。"
        title="还没有开始执行"
      />
    );
  }
  return (
    <ol className="space-y-3" aria-label="智能体执行进度">
      {run.steps.map((step) => (
        <li className="rounded-lg border p-4" key={step.id}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <strong>{agentToolLabel(step.tool_name)}</strong>
            <StatusBadge
              tone={
                step.status === "succeeded"
                  ? "success"
                  : step.status === "failed"
                    ? "danger"
                    : step.status === "awaiting_action_confirmation"
                      ? "warning"
                      : "info"
              }
            >
              {statusLabels[step.status]}
            </StatusBadge>
          </div>
          {step.safe_summary ? (
            <p className="mt-2 text-sm text-[var(--text-secondary)]">
              {step.safe_summary}
            </p>
          ) : null}
          {professional ? (
            <dl className="mt-3 grid grid-cols-1 gap-1 text-xs text-[var(--text-secondary)] sm:grid-cols-2">
              <div><dt className="inline">工具：</dt><dd className="inline">{step.tool_name} {step.tool_version}</dd></div>
              <div><dt className="inline">尝试次数：</dt><dd className="inline">{step.attempt_count}</dd></div>
            </dl>
          ) : null}
        </li>
      ))}
    </ol>
  );
}
