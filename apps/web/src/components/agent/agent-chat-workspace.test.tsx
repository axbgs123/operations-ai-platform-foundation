import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";

import type {
  AgentChatData,
  AgentChatSummaryData,
} from "@/lib/agent-api";

import { AgentChatWorkspace } from "./agent-chat-workspace";


afterEach(cleanup);

const account = {
  account_id: "11111111-1111-4111-8111-111111111111",
  name: "抖音科技账号",
  platform: "douyin" as const,
};
const summary: AgentChatSummaryData = {
  id: "22222222-2222-4222-8222-222222222222",
  title: "历史运营分析",
  status: "active",
  created_at: "2026-08-12T08:00:00Z",
  updated_at: "2026-08-12T08:00:00Z",
};
const detail: AgentChatData = {
  ...summary,
  workspace_id: "33333333-3333-4333-8333-333333333333",
  owner_member_id: "44444444-4444-4444-8444-444444444444",
  messages: [
    {
      id: "55555555-5555-4555-8555-555555555555",
      sequence_no: 1,
      role: "assistant",
      kind: "text",
      content: "你好，我可以帮你分析账号运营问题。",
      plan_id: null,
      run_id: null,
      created_at: "2026-08-12T08:00:00Z",
    },
  ],
};

test("creates a conversation and sends a message from the fixed composer", async () => {
  const createChat = vi.fn().mockResolvedValue(summary);
  const sendTurn = vi.fn().mockResolvedValue(detail);
  render(
    <AgentChatWorkspace
      accounts={[account]}
      actions={{
        archiveChat: vi.fn(),
        createChat,
        loadChat: vi.fn().mockResolvedValue(detail),
        sendTurn,
      }}
      initialChat={undefined}
      initialChats={[]}
      role="editor"
    />,
  );

  const input = screen.getByRole("textbox", { name: "给运营智能体发消息" });
  const user = userEvent.setup();
  await user.type(input, "你好");
  await user.click(screen.getByRole("button", { name: "发送" }));
  expect(createChat).toHaveBeenCalledTimes(1);
  expect(sendTurn).toHaveBeenCalledWith(
    summary.id,
    { content: "你好", account_id: account.account_id, platform: "douyin" },
  );
  expect(await screen.findByText("你好，我可以帮你分析账号运营问题。"))
    .toBeVisible();
  expect(input).toHaveValue("");
});

test("shows persistent history and viewer receives a read-only composer", () => {
  render(
    <AgentChatWorkspace
      accounts={[account]}
      actions={{
        archiveChat: vi.fn(),
        createChat: vi.fn(),
        loadChat: vi.fn(),
        sendTurn: vi.fn(),
      }}
      initialChat={detail}
      initialChats={[summary]}
      role="viewer"
    />,
  );

  expect(screen.getByRole("button", { name: "打开会话：历史运营分析" }))
    .toBeVisible();
  expect(screen.getByText("你好，我可以帮你分析账号运营问题。"))
    .toBeVisible();
  expect(screen.getByRole("textbox", { name: "给运营智能体发消息" }))
    .toBeDisabled();
  expect(screen.getByText("查看者只能阅读聊天和执行记录。"))
    .toBeVisible();
});

test("discloses external API use and supports keyboard send", async () => {
  const sendTurn = vi.fn().mockResolvedValue(detail);
  render(
    <AgentChatWorkspace
      accounts={[account]}
      actions={{
        archiveChat: vi.fn(),
        createChat: vi.fn(),
        loadChat: vi.fn(),
        sendTurn,
      }}
      initialChat={{ ...detail, messages: [] }}
      initialChats={[summary]}
      role="admin"
    />,
  );

  expect(screen.getByText(/使用你在工作区配置的模型服务/)).toBeVisible();
  const input = screen.getByRole("textbox", { name: "给运营智能体发消息" });
  await userEvent.setup().type(input, "你好{Meta>}{Enter}{/Meta}");
  expect(sendTurn).toHaveBeenCalledTimes(1);
});
