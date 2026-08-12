import type { ReactElement } from "react";

import type { AgentChatSummaryData } from "@/lib/agent-api";


export function ChatSidebar({
  canCreate,
  chats,
  onNew,
  onSelect,
  selectedId,
}: {
  canCreate: boolean;
  chats: AgentChatSummaryData[];
  onNew: () => void;
  onSelect: (chat: AgentChatSummaryData) => void;
  selectedId?: string;
}): ReactElement {
  return (
    <aside aria-label="历史会话" className="flex h-full min-h-0 flex-col border-r border-[var(--border)] bg-[var(--surface)]">
      {canCreate ? (
        <div className="border-b border-[var(--border)] p-4">
          <button
            className="w-full rounded-lg bg-[var(--brand)] px-4 py-2.5 text-sm font-semibold text-white"
            onClick={onNew}
            type="button"
          >
            ＋ 新对话
          </button>
        </div>
      ) : null}
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {chats.length ? (
          <ul className="space-y-1">
            {chats.map((chat) => (
              <li key={chat.id}>
                <button
                  aria-label={`打开会话：${chat.title}`}
                  aria-pressed={selectedId === chat.id}
                  className={`w-full rounded-lg px-3 py-3 text-left text-sm ${
                    selectedId === chat.id
                      ? "bg-[var(--brand-soft)] text-[var(--brand-strong)]"
                      : "text-[var(--text-primary)] hover:bg-slate-50"
                  }`}
                  onClick={() => onSelect(chat)}
                  type="button"
                >
                  <span className="block truncate font-medium">{chat.title}</span>
                  <span className="mt-1 block text-xs text-[var(--text-secondary)]">
                    {chat.status === "archived" ? "已归档" : "可继续对话"}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="p-3 text-sm leading-6 text-[var(--text-secondary)]">
            还没有历史对话。发送第一条消息后会自动保存。
          </p>
        )}
      </div>
    </aside>
  );
}
