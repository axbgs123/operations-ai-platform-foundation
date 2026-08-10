import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { ExtensionPairingPanel } from "./extension-pairing-panel";

const createExtensionPairingCode = vi.hoisted(() => vi.fn());
const writeText = vi.hoisted(() => vi.fn());
const ExtensionPairingApiError = vi.hoisted(() => class extends Error {
  constructor(readonly status: number) {
    super(status === 403 ? "当前角色无权生成连接码。" : "暂时无法生成连接码，请稍后重试。");
  }
});

vi.mock("@/lib/extension-pairing-api", () => ({
  createExtensionPairingCode,
  ExtensionPairingApiError,
}));

const firstPairing = {
  pairing_code: "ABCD2345",
  expires_at: "2026-08-10T01:05:00.000Z",
  workspace_id: "workspace-1",
  workspace_name: "运营工作区",
};

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(new Date("2026-08-10T01:00:00.000Z"));
  createExtensionPairingCode.mockReset();
  writeText.mockReset();
  sessionStorage.setItem("workspace_csrf", "csrf-token");
  Object.defineProperty(window.navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
});

afterEach(() => {
  cleanup();
  sessionStorage.clear();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

test("generates a server-expiring pairing code only for an editor", async () => {
  createExtensionPairingCode.mockResolvedValue(firstPairing);
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime, writeToClipboard: false });
  render(
    <ExtensionPairingPanel
      role="editor"
      triggerLabel="连接扩展"
      workspaceId="workspace-1"
    />,
  );

  await user.click(screen.getByRole("button", { name: "连接扩展" }));
  await user.click(screen.getByRole("button", { name: "生成连接码" }));

  expect(await screen.findByText("ABCD2345")).toBeVisible();
  expect(screen.getByText(/5 分钟内有效/)).toBeVisible();
  expect(screen.getByText("http://127.0.0.1:51201")).toBeVisible();
  expect(createExtensionPairingCode).toHaveBeenCalledWith(
    "workspace-1",
    "csrf-token",
  );
});

test("updates and expires its countdown from the server expiry timestamp", async () => {
  createExtensionPairingCode.mockResolvedValue(firstPairing);
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime, writeToClipboard: false });
  render(
    <ExtensionPairingPanel
      role="editor"
      triggerLabel="连接扩展"
      workspaceId="workspace-1"
    />,
  );

  await user.click(screen.getByRole("button", { name: "连接扩展" }));
  await user.click(screen.getByRole("button", { name: "生成连接码" }));
  await screen.findByText("ABCD2345");
  expect(screen.getByText("5 分钟内有效")).toBeVisible();

  act(() => vi.advanceTimersByTime(61_000));
  expect(screen.getByText("4 分钟内有效")).toBeVisible();
  act(() => vi.advanceTimersByTime(239_000));
  expect(screen.getByText("连接码已过期")).toBeVisible();
});

test("replaces a shown pairing code when regenerated", async () => {
  createExtensionPairingCode
    .mockResolvedValueOnce(firstPairing)
    .mockResolvedValueOnce({
      ...firstPairing,
      expires_at: "2026-08-10T01:08:00.000Z",
      pairing_code: "WXYZ6789",
    });
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime, writeToClipboard: false });
  render(
    <ExtensionPairingPanel
      role="admin"
      triggerLabel="连接扩展"
      workspaceId="workspace-1"
    />,
  );

  await user.click(screen.getByRole("button", { name: "连接扩展" }));
  await user.click(screen.getByRole("button", { name: "生成连接码" }));
  expect(await screen.findByText("ABCD2345")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "重新生成" }));

  expect(await screen.findByText("WXYZ6789")).toBeVisible();
  expect(screen.queryByText("ABCD2345")).not.toBeInTheDocument();
});

test("copies the displayed code and clears it when closed with focus returned", async () => {
  createExtensionPairingCode.mockResolvedValue(firstPairing);
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime, writeToClipboard: false });
  Object.defineProperty(window.navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
  render(
    <ExtensionPairingPanel
      role="admin"
      triggerLabel="连接扩展"
      workspaceId="workspace-1"
    />,
  );

  const trigger = screen.getByRole("button", { name: "连接扩展" });
  await user.click(trigger);
  await user.click(screen.getByRole("button", { name: "生成连接码" }));
  await screen.findByText("ABCD2345");
  await user.click(screen.getByRole("button", { name: "复制连接码" }));
  expect(writeText).toHaveBeenCalledWith("ABCD2345");

  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog", { name: "连接浏览器扩展" })).toBeNull();
  expect(screen.queryByText("ABCD2345")).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();

  await user.click(trigger);
  expect(screen.queryByText("ABCD2345")).not.toBeInTheDocument();
});

test("shows a safe message when copying the pairing code fails", async () => {
  createExtensionPairingCode.mockResolvedValue(firstPairing);
  writeText.mockRejectedValueOnce(new Error("PRIVATE_CLIPBOARD_FAILURE"));
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime, writeToClipboard: false });
  Object.defineProperty(window.navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
  render(
    <ExtensionPairingPanel
      role="admin"
      triggerLabel="连接扩展"
      workspaceId="workspace-1"
    />,
  );

  await user.click(screen.getByRole("button", { name: "连接扩展" }));
  await user.click(screen.getByRole("button", { name: "生成连接码" }));
  await screen.findByText("ABCD2345");
  await user.click(screen.getByRole("button", { name: "复制连接码" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("无法复制连接码，请手动复制后重试。");
  expect(document.body).not.toHaveTextContent("PRIVATE_CLIPBOARD_FAILURE");
});

test("starts only one request for rapid repeated generation clicks", async () => {
  createExtensionPairingCode.mockImplementation(() => new Promise(() => undefined));
  render(
    <ExtensionPairingPanel
      role="admin"
      triggerLabel="连接扩展"
      workspaceId="workspace-1"
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: "连接扩展" }));
  const generate = screen.getByRole("button", { name: "生成连接码" });
  fireEvent.click(generate);
  fireEvent.click(generate);

  expect(createExtensionPairingCode).toHaveBeenCalledTimes(1);
});

test("does not update after a pending generation resolves or rejects following unmount", async () => {
  let resolveRequest: (value: typeof firstPairing) => void;
  let rejectRequest: (reason: Error) => void;
  createExtensionPairingCode
    .mockImplementationOnce(() => new Promise<typeof firstPairing>((resolve) => {
      resolveRequest = resolve;
    }))
    .mockImplementationOnce(() => new Promise<typeof firstPairing>((_, reject) => {
      rejectRequest = reject;
    }));
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime, writeToClipboard: false });
  const first = render(
    <ExtensionPairingPanel
      role="admin"
      triggerLabel="连接扩展"
      workspaceId="workspace-1"
    />,
  );

  await user.click(screen.getByRole("button", { name: "连接扩展" }));
  await user.click(screen.getByRole("button", { name: "生成连接码" }));
  first.unmount();
  await act(async () => resolveRequest!(firstPairing));

  const second = render(
    <ExtensionPairingPanel
      role="admin"
      triggerLabel="连接扩展"
      workspaceId="workspace-1"
    />,
  );
  await user.click(screen.getByRole("button", { name: "连接扩展" }));
  await user.click(screen.getByRole("button", { name: "生成连接码" }));
  second.unmount();
  await act(async () => rejectRequest!(new Error("PRIVATE_LATE_FAILURE")));

  expect(document.body).not.toHaveTextContent("ABCD2345");
  expect(document.body).not.toHaveTextContent("PRIVATE_LATE_FAILURE");
});

test("focuses the dialog and cycles Tab in both directions before Escape returns focus", async () => {
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime, writeToClipboard: false });
  render(
    <ExtensionPairingPanel
      role="admin"
      triggerLabel="连接扩展"
      workspaceId="workspace-1"
    />,
  );

  const trigger = screen.getByRole("button", { name: "连接扩展" });
  await user.click(trigger);
  const [dismiss, close] = screen.getAllByRole("button", { name: "关闭" });
  const generate = screen.getByRole("button", { name: "生成连接码" });
  expect(dismiss).toHaveFocus();

  await user.keyboard("{Shift>}{Tab}{/Shift}");
  expect(close).toHaveFocus();
  await user.tab();
  expect(dismiss).toHaveFocus();
  await user.tab();
  expect(generate).toHaveFocus();
  await user.keyboard("{Escape}");
  expect(trigger).toHaveFocus();
});

test("does not restore a pairing code after closing while generation is pending", async () => {
  let resolveRequest: (value: typeof firstPairing) => void;
  createExtensionPairingCode.mockImplementation(() => new Promise<typeof firstPairing>((resolve) => {
    resolveRequest = resolve;
  }));
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime, writeToClipboard: false });
  render(
    <ExtensionPairingPanel
      role="admin"
      triggerLabel="连接扩展"
      workspaceId="workspace-1"
    />,
  );

  const trigger = screen.getByRole("button", { name: "连接扩展" });
  await user.click(trigger);
  await user.click(screen.getByRole("button", { name: "生成连接码" }));
  await user.click(screen.getByText("关闭"));
  await act(async () => {
    resolveRequest!(firstPairing);
  });
  await user.click(trigger);

  expect(screen.queryByText("ABCD2345")).not.toBeInTheDocument();
});

test("shows no pairing-code write action to a viewer", () => {
  render(
    <ExtensionPairingPanel
      role="viewer"
      triggerLabel="连接扩展"
      workspaceId="workspace-1"
    />,
  );

  expect(screen.getByText("查看者只能查看扩展连接说明。请联系管理员或编辑者生成连接码。")).toBeVisible();
  expect(screen.queryByRole("button", { name: "连接扩展" })).toBeNull();
  expect(screen.queryByRole("button", { name: "生成连接码" })).toBeNull();
});

test("keeps server error bodies out of the dialog", async () => {
  createExtensionPairingCode.mockRejectedValue(new Error("PRIVATE_SERVER_BODY"));
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime, writeToClipboard: false });
  render(
    <ExtensionPairingPanel
      role="admin"
      triggerLabel="连接扩展"
      workspaceId="workspace-1"
    />,
  );

  await user.click(screen.getByRole("button", { name: "连接扩展" }));
  await user.click(screen.getByRole("button", { name: "生成连接码" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("暂时无法生成连接码，请稍后重试。");
  expect(document.body).not.toHaveTextContent("PRIVATE_SERVER_BODY");
});

test("shows a mapped permission error without server response text", async () => {
  createExtensionPairingCode.mockRejectedValue(
    new ExtensionPairingApiError(403),
  );
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime, writeToClipboard: false });
  render(
    <ExtensionPairingPanel
      role="admin"
      triggerLabel="连接扩展"
      workspaceId="workspace-1"
    />,
  );

  await user.click(screen.getByRole("button", { name: "连接扩展" }));
  await user.click(screen.getByRole("button", { name: "生成连接码" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("当前角色无权生成连接码。");
});
