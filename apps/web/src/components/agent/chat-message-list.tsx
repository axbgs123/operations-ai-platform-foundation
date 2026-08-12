import type { ReactElement } from "react";

import type { AgentChatData } from "@/lib/agent-api";


export function ChatMessageList({
  chat,
  onOpenTasks,
}: {
  chat?: AgentChatData;
  onOpenTasks?: () => void;
}): ReactElement {
  if (!chat?.messages.length) {
    return (
      <div className="grid min-h-[24rem] place-items-center px-6 py-12 text-center">
        <div className="max-w-lg">
          <div className="mx-auto mb-4 grid size-12 place-items-center rounded-2xl bg-[var(--brand-soft)] text-xl text-[var(--brand-strong)]">
            运
          </div>
          <h2 className="text-xl font-semibold">今天想解决什么运营问题？</h2>
          <p className="mt-3 text-sm leading-6 text-[var(--text-secondary)]">
            例如：分析最近内容表现、找出数据下降原因，或为当前账号生成一份处理计划。
          </p>
        </div>
      </div>
    );
  }
  return (
    <ol
      aria-label="聊天消息"
      aria-live="polite"
      className="mx-auto w-full max-w-3xl space-y-5 px-4 py-8 sm:px-8"
    >
      {chat.messages.map((message) => {
        const user = message.role === "user";
        return (
          <li className={`flex ${user ? "justify-end" : "justify-start"}`} key={message.id}>
            <article
              className={`max-w-[86%] rounded-2xl px-4 py-3 text-sm leading-6 ${
                user
                  ? "bg-[var(--brand)] text-white"
                  : message.kind === "safe_error"
                    ? "border border-amber-200 bg-amber-50 text-amber-950"
                    : "border border-[var(--border)] bg-white text-[var(--text-primary)]"
              }`}
            >
              <p className="whitespace-pre-wrap">{message.content}</p>
              {message.kind === "plan" && message.plan_id ? (
                <div className="mt-3 rounded-lg border border-[var(--border)] bg-[var(--surface-muted)] p-3">
                  <strong className="block">处理计划已生成</strong>
                  <p className="mt-1 text-xs text-[var(--text-secondary)]">
                    计划不会自动执行，请先查看并批准。
                  </p>
                  <button className="mt-2 inline-block text-sm font-semibold text-[var(--brand-strong)]" onClick={onOpenTasks} type="button">
                    查看计划详情
                  </button>
                </div>
              ) : null}
            </article>
          </li>
        );
      })}
    </ol>
  );
}
