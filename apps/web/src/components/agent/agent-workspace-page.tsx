"use client";

import { useEffect, useState, type ReactElement } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import {
  approveAgentPlan,
  archiveAgentChat,
  AgentApiError,
  createAgentChat,
  createAgentPlan,
  decideAgentConfirmation,
  loadAgentBriefing,
  loadAgentChat,
  loadAgentChats,
  loadAgentConfirmations,
  loadAgentPlan,
  loadAgentRun,
  loadAgentRuns,
  recordBriefingDecision,
  rejectAgentPlan,
  sendAgentChatTurn,
  startAgentRun,
  type AgentWorkspaceFixture,
  type AgentChatData,
  type AgentChatSummaryData,
} from "@/lib/agent-api";

import { AgentWorkspace } from "./agent-workspace";
import { AgentChatWorkspace } from "./agent-chat-workspace";
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
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [fixture, setFixture] = useState<AgentWorkspaceFixture>();
  const [chats, setChats] = useState<AgentChatSummaryData[]>([]);
  const [chat, setChat] = useState<AgentChatData>();
  const [view, setView] = useState<"chat" | "tasks">("chat");
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
      loadAgentChats(workspaceId, controller.signal),
    ])
      .then(async ([briefing, confirmationList, run, chatList]) => {
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
        setChats(chatList);
        const requestedChat = searchParams.get("chat");
        const selected = chatList.find((item) => item.id === requestedChat)
          ?? chatList[0];
        if (selected) {
          setChat(await loadAgentChat(workspaceId, selected.id, controller.signal));
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => controller.abort();
  }, [context, searchParams, workspaceId]);

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

  const taskWorkspace = (
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

  return (
    <div className="space-y-4">
      <div aria-label="智能体工作方式" className="inline-flex rounded-xl border border-[var(--border)] bg-white p-1">
        <button
          aria-pressed={view === "chat"}
          className={`rounded-lg px-4 py-2 text-sm font-semibold ${view === "chat" ? "bg-[var(--brand)] text-white" : "text-[var(--text-secondary)]"}`}
          onClick={() => setView("chat")}
          type="button"
        >
          对话
        </button>
        <button
          aria-pressed={view === "tasks"}
          className={`rounded-lg px-4 py-2 text-sm font-semibold ${view === "tasks" ? "bg-[var(--brand)] text-white" : "text-[var(--text-secondary)]"}`}
          onClick={() => setView("tasks")}
          type="button"
        >
          任务与执行
        </button>
      </div>
      {view === "chat" ? (
        <AgentChatWorkspace
          key={chat?.id ?? "new-chat"}
          accounts={context.accounts}
          actions={{
            archiveChat: (chatId) => archiveAgentChat(workspaceId, chatId, csrf()),
            createChat: () => createAgentChat(workspaceId, csrf()),
            loadChat: (chatId) => loadAgentChat(workspaceId, chatId),
            sendTurn: async (chatId, body) => {
              const updated = await sendAgentChatTurn(
                workspaceId,
                chatId,
                body,
                csrf(),
              );
              const planId = [...updated.messages]
                .reverse()
                .find((message) => message.plan_id)?.plan_id;
              if (planId) {
                const plan = await loadAgentPlan(workspaceId, planId);
                setFixture((current) => current ? { ...current, plan } : current);
              }
              return updated;
            },
          }}
          initialChat={chat}
          initialChats={chats}
          onOpenTasks={() => setView("tasks")}
          onSelectedChatChange={(chatId) => {
            const query = new URLSearchParams(searchParams.toString());
            if (chatId) query.set("chat", chatId);
            else query.delete("chat");
            router.replace(`${pathname}${query.size ? `?${query}` : ""}`);
          }}
          role={context.role}
        />
      ) : taskWorkspace}
    </div>
  );
}
