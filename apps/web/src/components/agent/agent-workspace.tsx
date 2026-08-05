"use client";

import { useEffect, useMemo, useState, type ReactElement } from "react";

import type {
  AgentConfirmationData,
  AgentPlanCreate,
  AgentPlanData,
  AgentRunData,
  AgentWorkspaceFixture,
} from "@/lib/agent-api";

import { ConfirmationInbox } from "./confirmation-inbox";
import { DailySuggestionCard } from "./daily-suggestion-card";
import { agentToolLabel, RunTimeline } from "./run-timeline";
import { useOptionalExperiencePreferences } from "@/components/workbench/experience-preferences-context";
import {
  EmptyState,
  ErrorState,
  Panel,
  StatusBadge,
} from "@/components/workbench/ui";


type AgentActions = {
  createPlan?: (body: AgentPlanCreate) => Promise<AgentPlanData> | AgentPlanData | void;
  approvePlan?: (plan: AgentPlanData) => Promise<AgentPlanData>;
  rejectPlan?: (plan: AgentPlanData) => Promise<AgentPlanData>;
  startRun?: (plan: AgentPlanData) => Promise<AgentRunData>;
  loadRun?: (runId: string, signal?: AbortSignal) => Promise<AgentRunData>;
  loadConfirmations?: (
    signal?: AbortSignal,
  ) => Promise<AgentConfirmationData[]>;
  decideConfirmation?: (
    confirmation: AgentConfirmationData,
    decision: "approve" | "reject",
  ) => Promise<AgentConfirmationData>;
  deferBriefing?: () => Promise<void> | void;
  suppressBriefing?: () => Promise<void> | void;
};

const platformLabel = {
  douyin: "抖音",
  xiaohongshu: "小红书",
} as const;

const terminalStatuses = new Set<AgentRunData["status"]>([
  "succeeded",
  "rejected",
  "cancelled",
  "failed",
  "configuration_required",
  "compensation_required",
  "provider_outcome_unknown",
]);

export function AgentWorkspace({
  actions,
  fixture,
  role,
  workspaceId,
}: {
  actions: AgentActions;
  fixture: AgentWorkspaceFixture;
  role: "admin" | "editor" | "viewer";
  workspaceId: string;
}): ReactElement {
  const professional =
    useOptionalExperiencePreferences()?.copyMode === "professional";
  const [objective, setObjective] = useState(
    fixture.plan?.document.goal
      ?? fixture.briefing.primary?.safe_title
      ?? "",
  );
  const [accountId, setAccountId] = useState(
    fixture.plan?.account_id
      ?? fixture.briefing.primary?.account_id
      ?? fixture.accounts[0]?.account_id
      ?? "",
  );
  const [plan, setPlan] = useState(fixture.plan);
  const [run, setRun] = useState(fixture.run);
  const [confirmations, setConfirmations] = useState(fixture.confirmations);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const account = fixture.accounts.find((item) => item.account_id === accountId);
  const canEdit = role !== "viewer";
  const runId = run?.id;
  const runStatus = run?.status;
  const loadRunAction = actions.loadRun;
  const loadConfirmationsAction = actions.loadConfirmations;

  useEffect(() => {
    if (!runId || !runStatus || terminalStatuses.has(runStatus) || !loadRunAction) return;
    const controller = new AbortController();
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const latest = await loadRunAction(runId, controller.signal);
        if (controller.signal.aborted) return;
        setRun(latest);
        if (
          latest.status === "awaiting_action_confirmation"
          && loadConfirmationsAction
        ) {
          const latestConfirmations = await loadConfirmationsAction(
            controller.signal,
          );
          if (controller.signal.aborted) return;
          setConfirmations(latestConfirmations);
        }
        if (!terminalStatuses.has(latest.status)) {
          const delays = [2000, 4000, 8000, 10000];
          timer = setTimeout(poll, delays[Math.min(attempt++, 3)]);
        }
      } catch {
        if (!controller.signal.aborted) {
          timer = setTimeout(poll, 10000);
        }
      }
    };
    timer = setTimeout(poll, 2000);
    return () => {
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [loadConfirmationsAction, loadRunAction, runId, runStatus]);

  const completedSummaries = useMemo(
    () => run?.steps.filter((step) => step.safe_summary) ?? [],
    [run],
  );

  async function createPlan() {
    if (!account || !objective.trim() || !actions.createPlan) return;
    setBusy(true);
    setError(null);
    try {
      const created = await actions.createPlan({
        objective: objective.trim(),
        account_id: account.account_id,
        platform: account.platform,
        briefing_id: fixture.briefing.id,
        planner: "deterministic",
      });
      if (created) setPlan(created);
    } catch {
      setError("处理计划生成失败，请稍后重试。");
    } finally {
      setBusy(false);
    }
  }

  async function approveAndStart() {
    if (!plan || !actions.approvePlan || !actions.startRun) return;
    setBusy(true);
    setError(null);
    try {
      const approved = await actions.approvePlan(plan);
      setPlan(approved);
      setRun(await actions.startRun(approved));
    } catch {
      setError("计划没有开始执行。请检查配置或稍后重试。");
    } finally {
      setBusy(false);
    }
  }

  async function startApprovedPlan() {
    if (!plan || !actions.startRun) return;
    setBusy(true);
    setError(null);
    try {
      setRun(await actions.startRun(plan));
    } catch {
      setError("执行任务暂时没有启动，请稍后重试。");
    } finally {
      setBusy(false);
    }
  }

  async function reject() {
    if (!plan || !actions.rejectPlan) return;
    setBusy(true);
    try {
      setPlan(await actions.rejectPlan(plan));
    } catch {
      setError("计划暂时无法拒绝，请稍后重试。");
    } finally {
      setBusy(false);
    }
  }

  async function decide(
    confirmation: AgentConfirmationData,
    decision: "approve" | "reject",
  ) {
    if (!actions.decideConfirmation) return;
    try {
      const updated = await actions.decideConfirmation(confirmation, decision);
      setConfirmations((items) =>
        items.map((item) => item.id === updated.id ? updated : item),
      );
    } catch {
      setError("确认结果没有保存，请刷新后重试。");
    }
  }

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">运营智能体</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-[var(--text-secondary)]">
          告诉它你想解决的运营问题。它会先给出可检查的计划，获得批准后再执行；需要写入正式记录时会停下来等你确认。
        </p>
      </header>

      <DailySuggestionCard
        accounts={fixture.accounts}
        briefing={fixture.briefing}
        onDefer={() => actions.deferBriefing?.()}
        onSuppress={() => actions.suppressBriefing?.()}
        role={role}
        workspaceId={workspaceId}
      />

      {error ? (
        <ErrorState description={error} title="智能体操作未完成" />
      ) : null}

      <Panel
        description="先锁定一个平台账号，避免不同账号或平台的数据混在一起。"
        title="目标与账号"
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="text-sm font-medium">
            这次想解决什么
            <textarea
              className="mt-2 min-h-24 w-full rounded-lg border bg-white p-3"
              disabled={!canEdit || Boolean(plan)}
              onChange={(event) => setObjective(event.target.value)}
              value={objective}
            />
          </label>
          <label className="text-sm font-medium">
            执行账号
            <select
              className="mt-2 w-full rounded-lg border bg-white p-3"
              disabled={!canEdit || Boolean(plan)}
              onChange={(event) => setAccountId(event.target.value)}
              value={accountId}
            >
              {fixture.accounts.map((item) => (
                <option key={item.account_id} value={item.account_id}>
                  {platformLabel[item.platform]} · {item.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        {role === "viewer" ? (
          <p className="mt-4 rounded-lg bg-slate-50 p-3 text-sm">
            查看者可以查看进度和结果，但不能批准或执行操作。
          </p>
        ) : null}
      </Panel>

      <div id="agent-plan">
        <Panel
          description="计划只使用系统允许的工具；批准前不会开始执行。"
          title="处理计划"
        >
          {!plan ? (
            canEdit ? (
              <button
                className="rounded-lg bg-[var(--brand)] px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
                disabled={busy || !objective.trim() || !account}
                onClick={createPlan}
                type="button"
              >
                生成处理计划
              </button>
            ) : (
              <EmptyState
                description="管理员或编辑者生成计划后，你可以在这里查看。"
                title="还没有处理计划"
              />
            )
          ) : (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <strong>{plan.document.goal}</strong>
                <StatusBadge tone={plan.status === "approved" ? "success" : plan.status === "rejected" ? "danger" : "info"}>
                  {plan.status === "draft" ? "等待批准" : plan.status === "approved" ? "已批准" : plan.status === "rejected" ? "已拒绝" : "已失效"}
                </StatusBadge>
              </div>
              <ol className="space-y-2">
                {plan.document.steps.map((step) => (
                  <li className="rounded-lg bg-slate-50 p-3 text-sm" key={step.step_index}>
                    <strong>{step.step_index + 1}. {agentToolLabel(step.tool_name)}</strong>
                    <p className="mt-1 text-[var(--text-secondary)]">{step.rationale}</p>
                    {professional ? (
                      <p className="mt-1 text-xs text-[var(--text-secondary)]">
                        {step.tool_name} · {step.tool_version}
                      </p>
                    ) : null}
                  </li>
                ))}
              </ol>
              {canEdit && plan.status === "draft" ? (
                <div className="flex flex-wrap gap-2">
                  <button
                    className="rounded-lg bg-[var(--brand)] px-4 py-2 text-sm font-semibold text-white"
                    disabled={busy}
                    onClick={approveAndStart}
                    type="button"
                  >
                    批准计划
                  </button>
                  <button
                    className="rounded-lg border px-4 py-2 text-sm font-semibold"
                    disabled={busy}
                    onClick={reject}
                    type="button"
                  >
                    拒绝计划
                  </button>
                </div>
              ) : null}
              {canEdit && plan.status === "approved" && !run ? (
                <button
                  className="rounded-lg bg-[var(--brand)] px-4 py-2 text-sm font-semibold text-white"
                  disabled={busy}
                  onClick={startApprovedPlan}
                  type="button"
                >
                  开始执行
                </button>
              ) : null}
            </div>
          )}
        </Panel>
      </div>

      <Panel
        description="页面关闭后仍会以服务器记录为准，重新打开不会靠浏览器猜测进度。"
        title="执行进度"
      >
        <RunTimeline run={run} />
      </Panel>

      <Panel
        description="普通只读和草稿步骤会自动继续；受保护的写入必须由发起成员确认。"
        title="需要你确认"
      >
        <ConfirmationInbox
          confirmations={confirmations}
          onDecision={decide}
          role={role}
        />
      </Panel>

      <Panel
        description="只展示安全摘要；正文、提示词、密钥和供应商原始响应不会出现在这里。"
        title="优化结果"
      >
        <p className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          辅助判断，不保证通过平台审核
        </p>
        {completedSummaries.length ? (
          <ul className="space-y-2">
            {completedSummaries.map((step) => (
              <li className="rounded-lg border p-4 text-sm" key={step.id}>
                <strong>{agentToolLabel(step.tool_name)}</strong>
                <p className="mt-1 text-[var(--text-secondary)]">{step.safe_summary}</p>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState
            description="执行完成后，这里会显示可安全查看的结果摘要。"
            title="还没有优化结果"
          />
        )}
        {professional && run ? (
          <dl className="mt-4 grid grid-cols-1 gap-2 rounded-lg bg-slate-50 p-4 text-xs sm:grid-cols-3">
            <div><dt>运行 ID</dt><dd className="break-all">{run.id}</dd></div>
            <div><dt>Provider / 模型</dt><dd>{run.usage.provider ?? "未调用"} / {run.usage.model_id ?? "未调用"}</dd></div>
            <div><dt>API 尝试 / Token</dt><dd>{run.usage.attempt_count} / {run.usage.input_tokens + run.usage.output_tokens}</dd></div>
            <div><dt>运行状态 / 错误码</dt><dd>{run.status} / {run.safe_error_code ?? "无"}</dd></div>
          </dl>
        ) : null}
      </Panel>
    </div>
  );
}
