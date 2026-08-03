import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import EnterPage from "./page";

const { enterWorkspaceMock, onboardWorkspaceOwnerMock } = vi.hoisted(() => ({
  enterWorkspaceMock: vi.fn(),
  onboardWorkspaceOwnerMock: vi.fn(),
}));

vi.mock("@/lib/workspace-api", () => ({
  enterWorkspace: enterWorkspaceMock,
  onboardWorkspaceOwner: onboardWorkspaceOwnerMock,
}));

const locationAssignMock = vi.fn();

beforeEach(() => {
  enterWorkspaceMock.mockReset();
  onboardWorkspaceOwnerMock.mockReset();
  locationAssignMock.mockReset();
  sessionStorage.clear();
  vi.stubGlobal("location", { assign: locationAssignMock });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("offers persistent, accessible create-team and join-team paths", () => {
  render(<EnterPage />);

  expect(
    screen.getByRole("heading", { name: "进入你的运营工作区" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "创建团队" }),
  ).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: "加入团队" })).toHaveAttribute(
    "aria-pressed",
    "false",
  );
  expect(screen.getByLabelText("团队名称")).toBeInTheDocument();
  expect(screen.getByLabelText("我的名称")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "创建团队并进入" }),
  ).toBeInTheDocument();
  expect(screen.getByText(/创建团队不需要邀请码/)).toBeInTheDocument();
  expect(
    screen.getByText(/换浏览器或换电脑后，需要另一个管理员邀请码/),
  ).toBeInTheDocument();
});

test("creates the first owner without sending an invite code", async () => {
  const user = userEvent.setup();
  onboardWorkspaceOwnerMock.mockResolvedValue({
    workspace_id: "workspace-owner",
    member_id: "member-owner",
    csrf_token: "csrf-owner",
  });
  render(<EnterPage />);

  await user.type(screen.getByLabelText("团队名称"), "C哥内容团队");
  await user.type(screen.getByLabelText("我的名称"), "小白");
  await user.click(screen.getByRole("button", { name: "创建团队并进入" }));

  await waitFor(() => {
    expect(onboardWorkspaceOwnerMock).toHaveBeenCalledWith(
      "C哥内容团队",
      "小白",
    );
  });
  expect(enterWorkspaceMock).not.toHaveBeenCalled();
  expect(sessionStorage.getItem("workspace_csrf")).toBe("csrf-owner");
  expect(locationAssignMock).toHaveBeenCalledWith(
    "/workspaces/workspace-owner",
  );
});

test("keeps invite joining independent from owner onboarding", async () => {
  const user = userEvent.setup();
  enterWorkspaceMock.mockResolvedValue({
    workspace_id: "workspace-invite",
    member_id: "member-editor",
    csrf_token: "csrf-editor",
  });
  render(<EnterPage />);

  await user.click(
    screen.getByRole("button", { name: "加入团队", pressed: false }),
  );
  expect(screen.getByLabelText("邀请码")).toBeInTheDocument();
  expect(screen.getByLabelText("我的名称")).toBeInTheDocument();
  await user.type(screen.getByLabelText("邀请码"), "synthetic.invite");
  await user.type(screen.getByLabelText("我的名称"), "运营同事");
  await user.click(
    within(screen.getByRole("form", { name: "加入团队表单" })).getByRole(
      "button",
      { name: "加入团队" },
    ),
  );

  await waitFor(() => {
    expect(enterWorkspaceMock).toHaveBeenCalledWith(
      "synthetic.invite",
      "运营同事",
    );
  });
  expect(onboardWorkspaceOwnerMock).not.toHaveBeenCalled();
  expect(sessionStorage.getItem("workspace_csrf")).toBe("csrf-editor");
  expect(locationAssignMock).toHaveBeenCalledWith(
    "/workspaces/workspace-invite",
  );
});

test("blocks duplicate owner submissions and allows a safe retry after failure", async () => {
  const user = userEvent.setup();
  let rejectOnboarding: (reason?: unknown) => void = () => undefined;
  onboardWorkspaceOwnerMock.mockImplementation(
    () =>
      new Promise((_, reject) => {
        rejectOnboarding = reject;
      }),
  );
  render(<EnterPage />);

  await user.type(screen.getByLabelText("团队名称"), "合成测试团队");
  await user.type(screen.getByLabelText("我的名称"), "测试管理员");
  const submit = screen.getByRole("button", { name: "创建团队并进入" });
  await user.click(submit);

  expect(submit).toBeDisabled();
  await user.click(submit);
  expect(onboardWorkspaceOwnerMock).toHaveBeenCalledTimes(1);

  rejectOnboarding(new Error("provider detail must stay hidden"));

  expect(
    await screen.findByRole("alert", {
      name: "创建失败，请稍后重试",
    }),
  ).toBeInTheDocument();
  expect(submit).toBeEnabled();
});
