import type { KeyboardEvent, ReactElement } from "react";

import type { AgentAccount } from "@/lib/agent-api";


const platformLabel = { douyin: "抖音", xiaohongshu: "小红书" } as const;

export function ChatComposer({
  accountId,
  accounts,
  busy,
  disabled,
  onAccountChange,
  onChange,
  onSend,
  value,
}: {
  accountId: string;
  accounts: AgentAccount[];
  busy: boolean;
  disabled: boolean;
  onAccountChange: (value: string) => void;
  onChange: (value: string) => void;
  onSend: () => void;
  value: string;
}): ReactElement {
  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      if (!disabled && !busy && value.trim()) onSend();
    }
  }
  return (
    <div className="border-t border-[var(--border)] bg-[var(--surface)] px-4 py-4 sm:px-8">
      <div className="mx-auto max-w-3xl">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <label className="flex items-center gap-2 text-xs text-[var(--text-secondary)]">
            当前账号
            <select
              aria-label="当前聊天账号"
              className="rounded-lg border border-[var(--border)] bg-white px-2 py-1.5 text-sm text-[var(--text-primary)]"
              disabled={disabled || busy || !accounts.length}
              onChange={(event) => onAccountChange(event.target.value)}
              value={accountId}
            >
              {!accounts.length ? <option value="">还没有账号</option> : null}
              {accounts.map((account) => (
                <option key={account.account_id} value={account.account_id}>
                  {platformLabel[account.platform]} · {account.name}
                </option>
              ))}
            </select>
          </label>
          <span className="text-xs text-[var(--text-secondary)]">⌘/Ctrl + Enter 发送</span>
        </div>
        <div className="flex items-end gap-2 rounded-2xl border border-[var(--border-strong)] bg-white p-2 shadow-sm focus-within:ring-2 focus-within:ring-[var(--focus)]">
          <textarea
            aria-label="给运营智能体发消息"
            className="min-h-20 flex-1 resize-none border-0 bg-transparent p-2 text-sm outline-none"
            disabled={disabled}
            maxLength={4000}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={disabled ? "当前会话为只读" : "描述你想分析或处理的运营问题…"}
            value={value}
          />
          <button
            className="rounded-xl bg-[var(--brand)] px-4 py-2.5 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
            disabled={disabled || busy || !value.trim()}
            onClick={onSend}
            type="button"
          >
            {busy ? "发送中" : "发送"}
          </button>
        </div>
        <p className="mt-2 text-xs leading-5 text-[var(--text-secondary)]">
          使用你在工作区配置的模型服务，可能由服务商计费；计划仍需人工批准后才会执行。
        </p>
      </div>
    </div>
  );
}
