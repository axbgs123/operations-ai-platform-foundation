"use client";

import { useEffect, useState, type ReactElement } from "react";

import {
  approveAgentPlan,
  AgentApiError,
  createAgentPlan,
  decideAgentConfirmation,
  loadAgentBriefing,
  loadAgentConfirmations,
  loadAgentPlan,
  loadAgentRun,
  loadAgentRuns,
  recordBriefingDecision,
  rejectAgentPlan,
  startAgentRun,
  type AgentWorkspaceFixture,
} from "@/lib/agent-api";

import { AgentWorkspace } from "./agent-workspace";
import { ErrorState, Skeleton } from "@/components/workbench/ui";
import { useWorkbenchShellContext } from "@/components/workbench/workspace-shell";


const csrf = () => sessionStorage.getItem("workspace_csrf") ?? "";
const planKey = (memberId: string) => `operations-ai:agent:selected-plan:${memberId}`;
const runKey = (memberId: string) => `operations-ai:agent:selected-run:${memberId}`;

export function AgentWorkspacePage({
  workspaceId,
}: {
  workspaceId: string;
}): ReactElement {
  const context = useWorkbenchShellContext();
  const [fixture, setFixture] = useState<AgentWorkspaceFixture>();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!context) return;
    const controller = new AbortController();
    const selectedRunId = localStorage.getItem(runKey(context.member_id));
    const selectedPlanId = localStorage.getItem(planKey(context.member_id));
    const initialRun = async () => {
      if (selectedRunId) {
        try {
          return await loadAgentRun(
            workspaceId,
            selectedRunId,
            controller.signal,
          );
        } catch (error) {
          if (!(error instanceof AgentApiError) || error.status !== 404) {
            throw error;
          }
          localStorage.removeItem(runKey(context.member_id));
        }
      }
      return loadAgentRuns(workspaceId, controller.signal)
        .then((items) => items[0]);
    };
    Promise.all([
      loadAgentBriefing(workspaceId, controller.signal),
      loadAgentConfirmations(workspaceId, controller.signal),
      initialRun(),
    ])
      .then(async ([briefing, confirmationList, run]) => {
        let plan;
        try {
          plan = run
            ? await loadAgentPlan(workspaceId, run.plan_id, controller.signal)
            : selectedPlanId
              ? await loadAgentPlan(
                  workspaceId,
                  selectedPlanId,
                  controller.signal,
                )
              : undefined;
        } catch (error) {
          if (!(error instanceof AgentApiError) || error.status !== 404) {
            throw error;
          }
          localStorage.removeItem(planKey(context.member_id));
        }
        setFixture({
          accounts: context.accounts,
          briefing,
          confirmations: confirmationList.items,
          plan,
          run,
        });
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => controller.abort();
  }, [context, workspaceId]);

  if (!context) return <Skeleton label="正在读取工作区" />;
  if (failed) {
    return (
      <ErrorState
        description="服务器中的计划和进度暂时无法读取，已有记录不会丢失。"
        title="运营智能体加载失败"
      />
    );
  }
  if (!fixture) return <Skeleton label="正在读取运营智能体" />;

  return (
    <AgentWorkspace
      actions={{
        createPlan: async (body) => {
          const plan = await createAgentPlan(workspaceId, body, csrf());
          localStorage.setItem(planKey(context.member_id), plan.id);
          return plan;
        },
        approvePlan: (plan) => approveAgentPlan(workspaceId, plan.id, csrf()),
        rejectPlan: (plan) => rejectAgentPlan(workspaceId, plan.id, csrf()),
        startRun: async (plan) => {
          const run = await startAgentRun(workspaceId, plan.id, csrf());
          localStorage.setItem(runKey(context.member_id), run.id);
          return run;
        },
        loadRun: (runId, signal) => loadAgentRun(workspaceId, runId, signal),
        loadConfirmations: (signal) =>
          loadAgentConfirmations(workspaceId, signal)
            .then(({ items }) => items),
        decideConfirmation: (confirmation, decision) =>
          decideAgentConfirmation(
            workspaceId,
            confirmation,
            decision,
            csrf(),
          ),
        deferBriefing: async () => {
          await recordBriefingDecision(
            workspaceId,
            fixture.briefing,
            "defer",
            csrf(),
          );
        },
        suppressBriefing: async () => {
          await recordBriefingDecision(
            workspaceId,
            fixture.briefing,
            "suppress_kind",
            csrf(),
          );
        },
      }}
      fixture={fixture}
      role={context.role}
      workspaceId={workspaceId}
    />
  );
}
