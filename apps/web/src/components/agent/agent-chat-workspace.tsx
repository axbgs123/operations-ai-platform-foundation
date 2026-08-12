"use client";

import { useState, type ReactElement } from "react";

import type {
  AgentAccount,
  AgentChatData,
  AgentChatSummaryData,
  AgentChatTurnCreate,
} from "@/lib/agent-api";

import { ChatComposer } from "./chat-composer";
import { ChatMessageList } from "./chat-message-list";
import { ChatSidebar } from "./chat-sidebar";


export type AgentChatActions = {
  createChat: () => Promise<AgentChatSummaryData>;
  loadChat: (chatId: string) => Promise<AgentChatData>;
  sendTurn: (chatId: string, body: AgentChatTurnCreate) => Promise<AgentChatData>;
  archiveChat: (chatId: string) => Promise<AgentChatSummaryData>;
};

export function AgentChatWorkspace({
  accounts,
  actions,
  initialChat,
  initialChats,
  onOpenTasks,
  onSelectedChatChange,
  role,
}: {
  accounts: AgentAccount[];
  actions: AgentChatActions;
  initialChat?: AgentChatData;
  initialChats: AgentChatSummaryData[];
  onOpenTasks?: () => void;
  onSelectedChatChange?: (chatId?: string) => void;
  role: "admin" | "editor" | "viewer";
}): ReactElement {
  const [chats, setChats] = useState(initialChats);
  const [chat, setChat] = useState(initialChat);
  const [message, setMessage] = useState("");
  const [accountId, setAccountId] = useState(accounts[0]?.account_id ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const account = accounts.find((item) => item.account_id === accountId);
  const readOnly = role === "viewer" || chat?.status === "archived";

  async function selectChat(summary: AgentChatSummaryData) {
    setBusy(true);
    setError(undefined);
    try {
      const selected = await actions.loadChat(summary.id);
      setChat(selected);
      onSelectedChatChange?.(selected.id);
      setDrawerOpen(false);
    } catch {
      setError("这条历史会话暂时无法读取，请稍后重试。");
    } finally {
      setBusy(false);
    }
  }

  function newChat() {
    setChat(undefined);
    setMessage("");
    setError(undefined);
    onSelectedChatChange?.(undefined);
    setDrawerOpen(false);
  }

  async function send() {
    const content = message.trim();
    if (!content || readOnly || busy) return;
    setBusy(true);
    setError(undefined);
    try {
      let active = chat;
      if (!active) {
        const created = await actions.createChat();
        setChats((items) => [created, ...items]);
        active = {
          ...created,
          workspace_id: "00000000-0000-0000-0000-000000000000",
          owner_member_id: "00000000-0000-0000-0000-000000000000",
          messages: [],
        };
        onSelectedChatChange?.(created.id);
      }
      const body: AgentChatTurnCreate = account
        ? {
            content,
            account_id: account.account_id,
            platform: account.platform,
          }
        : { content, account_id: null, platform: null };
      const updated = await actions.sendTurn(active.id, body);
      setChat(updated);
      setChats((items) => [
        {
          id: updated.id,
          title: updated.title,
          status: updated.status,
          created_at: updated.created_at,
          updated_at: updated.updated_at,
        },
        ...items.filter((item) => item.id !== updated.id),
      ]);
      setMessage("");
    } catch {
      setError("消息没有发送成功，已输入的内容仍保留在输入框中。");
    } finally {
      setBusy(false);
    }
  }

  async function archive() {
    if (!chat || readOnly || busy) return;
    setBusy(true);
    try {
      const archived = await actions.archiveChat(chat.id);
      setChat({ ...chat, status: archived.status, updated_at: archived.updated_at });
      setChats((items) => items.map((item) => item.id === archived.id ? archived : item));
    } catch {
      setError("会话暂时无法归档，请稍后重试。");
    } finally {
      setBusy(false);
    }
  }

  const sidebar = (
    <ChatSidebar
      canCreate={role !== "viewer"}
      chats={chats}
      onNew={newChat}
      onSelect={selectChat}
      selectedId={chat?.id}
    />
  );

  return (
    <div className="-m-4 min-h-[calc(100vh-8rem)] overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)] sm:-m-6">
      <header className="flex items-center justify-between gap-3 border-b border-[var(--border)] px-4 py-3 sm:px-6">
        <div>
          <h1 className="text-lg font-semibold">运营智能体</h1>
          <p className="text-xs text-[var(--text-secondary)]">聊天记录会保存在服务器中</p>
        </div>
        <div className="flex items-center gap-2">
          <button className="rounded-lg border px-3 py-2 text-sm md:hidden" onClick={() => setDrawerOpen(true)} type="button">
            历史会话
          </button>
          {chat && role !== "viewer" ? (
            <button className="rounded-lg border px-3 py-2 text-sm disabled:opacity-50" disabled={busy || chat.status === "archived"} onClick={archive} type="button">
              归档
            </button>
          ) : null}
        </div>
      </header>
      {error ? (
        <div role="alert" className="border-b border-red-200 bg-red-50 px-4 py-2 text-sm text-red-800">{error}</div>
      ) : null}
      <div className="grid min-h-[calc(100vh-12rem)] md:grid-cols-[280px_minmax(0,1fr)]">
        <div className="hidden min-h-0 md:block">{sidebar}</div>
        <main className="flex min-h-0 flex-col bg-[var(--surface-muted)]">
          <div className="min-h-0 flex-1 overflow-y-auto">
            <ChatMessageList chat={chat} onOpenTasks={onOpenTasks} />
          </div>
          {role === "viewer" ? (
            <p className="border-t border-[var(--border)] bg-white px-4 pt-3 text-center text-sm text-[var(--text-secondary)]">
              查看者只能阅读聊天和执行记录。
            </p>
          ) : null}
          <ChatComposer
            accountId={accountId}
            accounts={accounts}
            busy={busy}
            disabled={readOnly}
            onAccountChange={setAccountId}
            onChange={setMessage}
            onSend={send}
            value={message}
          />
        </main>
      </div>
      {drawerOpen ? (
        <div aria-modal="true" className="fixed inset-0 z-50 grid grid-cols-[min(85vw,300px)_1fr] bg-black/30 md:hidden" role="dialog">
          <div className="min-h-0 bg-white">{sidebar}</div>
          <button aria-label="关闭历史会话" onClick={() => setDrawerOpen(false)} type="button" />
        </div>
      ) : null}
    </div>
  );
}
