import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { AccountCreatePanel } from "./account-create-panel";

const { createAccount, push } = vi.hoisted(() => ({
  createAccount: vi.fn(),
  push: vi.fn(),
}));

vi.mock("@/lib/account-api", () => ({ createAccount }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

beforeEach(() => {
  createAccount.mockReset();
  push.mockReset();
  sessionStorage.clear();
  sessionStorage.setItem("workspace_csrf", "csrf-token");
});

afterEach(cleanup);

test("creates an account with safe defaults and opens its scoped dashboard", async () => {
  const user = userEvent.setup();
  createAccount.mockResolvedValue({
    id: "account-new",
    workspace_id: "workspace-1",
    platform: "xiaohongshu",
    name: "穿搭灵感号",
    objective_profile: {
      id: "objective-1",
      version: 1,
      objectives: ["提升内容表现"],
      metric_weights: { views: 1 },
    },
    benchmark_profile: { id: "benchmark-1", version: 1, sample_size: 30 },
  });

  render(<AccountCreatePanel workspaceId="workspace-1" />);
  await user.selectOptions(screen.getByRole("combobox", { name: "所属平台" }), "xiaohongshu");
  await user.type(screen.getByRole("textbox", { name: "账号名称" }), "穿搭灵感号");
  await user.click(screen.getByRole("button", { name: "创建账号" }));

  await waitFor(() => expect(createAccount).toHaveBeenCalledWith(
    "workspace-1",
    "csrf-token",
    {
      platform: "xiaohongshu",
      name: "穿搭灵感号",
      objectives: ["提升内容表现"],
      metric_weights: { views: 1 },
      benchmark_sample_size: 30,
    },
  ));
  expect(push).toHaveBeenCalledWith(
    "/workspaces/workspace-1/accounts/account-new?platform=xiaohongshu&account=account-new",
  );
});

test("prevents duplicate submission while account creation is pending", async () => {
  const user = userEvent.setup();
  createAccount.mockImplementation(() => new Promise(() => undefined));

  render(<AccountCreatePanel workspaceId="workspace-1" />);
  await user.type(screen.getByRole("textbox", { name: "账号名称" }), "抖音主账号");
  await user.click(screen.getByRole("button", { name: "创建账号" }));

  expect(screen.getByRole("button", { name: "正在创建账号" })).toBeDisabled();
  expect(createAccount).toHaveBeenCalledTimes(1);
});

test("keeps the entered name and offers a safe retry after failure", async () => {
  const user = userEvent.setup();
  createAccount.mockRejectedValue(new Error("synthetic internal detail"));

  render(<AccountCreatePanel workspaceId="workspace-1" />);
  const name = screen.getByRole("textbox", { name: "账号名称" });
  await user.type(name, "失败重试账号");
  await user.click(screen.getByRole("button", { name: "创建账号" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "账号创建失败，请检查信息后重试。",
  );
  expect(name).toHaveValue("失败重试账号");
  expect(screen.getByRole("button", { name: "创建账号" })).toBeEnabled();
  expect(document.body.textContent).not.toContain("synthetic internal detail");
});
