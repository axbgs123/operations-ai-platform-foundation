import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import {
  readWorkspaceSessionRecovery,
  writeWorkspaceSessionRecovery,
} from "@/lib/workspace-session-recovery";

import EnterPage from "./page";

const {
  enterWorkspaceMock,
  loadWorkbenchContextMock,
  onboardWorkspaceOwnerMock,
  WorkbenchApiErrorMock,
} = vi.hoisted(() => {
  class WorkbenchApiErrorMock extends Error {
    constructor(readonly status: number) {
      super("workbench request failed");
    }
  }
  return {
    enterWorkspaceMock: vi.fn(),
    loadWorkbenchContextMock: vi.fn(),
    onboardWorkspaceOwnerMock: vi.fn(),
    WorkbenchApiErrorMock,
  };
});

vi.mock("@/lib/workspace-api", () => ({
  enterWorkspace: enterWorkspaceMock,
  onboardWorkspaceOwner: onboardWorkspaceOwnerMock,
}));

vi.mock("@/lib/workbench-api", () => ({
  loadWorkbenchContext: loadWorkbenchContextMock,
  WorkbenchApiError: WorkbenchApiErrorMock,
}));

const locationAssignMock = vi.fn();
const ownerWorkspaceId = "019fee9a-cb94-79b3-a0f0-3d6116c33d1d";
const ownerMemberId = "019fee9a-cb95-70ab-8b01-123456789abc";
const editorWorkspaceId = "019fee9a-cb96-7448-842b-123456789abc";
const editorMemberId = "019fee9a-cb97-7448-842b-123456789abc";
const rememberedSession = {
  workspaceId: ownerWorkspaceId,
  memberId: ownerMemberId,
  csrfToken: "csrf-token-with-sufficient-length",
};
const rememberedContext = {
  workspace_id: ownerWorkspaceId,
  workspace_name: "原来的团队",
  member_id: ownerMemberId,
  member_display_name: "原管理员",
  role: "admin" as const,
  accounts: [],
  failed_task_count: 0,
};

beforeEach(() => {
  enterWorkspaceMock.mockReset();
  loadWorkbenchContextMock.mockReset();
  onboardWorkspaceOwnerMock.mockReset();
  locationAssignMock.mockReset();
  localStorage.clear();
  sessionStorage.clear();
  vi.stubGlobal("location", { assign: locationAssignMock });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("offers persistent, accessible create-team and join-team paths", async () => {
  render(<EnterPage />);

  expect(
    await screen.findByRole("heading", { name: "进入你的运营工作区" }),
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

test("uses the approved light workbench tokens for the entry surface and text", async () => {
  render(<EnterPage />);

  const main = screen.getByRole("main");
  const entryCard = await screen.findByRole("region", {
    name: "进入你的运营工作区",
  });
  expect(main).toHaveClass(
    "bg-[var(--canvas)]",
    "text-[var(--text-primary)]",
  );
  expect(main).not.toHaveClass("bg-slate-950", "bg-slate-900");
  expect(entryCard).toHaveClass(
    "border-[var(--border)]",
    "bg-[var(--surface)]",
  );
  expect(entryCard).not.toHaveClass("bg-slate-950", "bg-slate-900");
  expect(
    screen.getByText(
      "创建新团队，或使用管理员提供的独立邀请码加入已有团队。",
    ),
  ).toHaveClass("text-[var(--text-secondary)]");
});

test("creates the first owner without sending an invite code", async () => {
  const user = userEvent.setup();
  onboardWorkspaceOwnerMock.mockResolvedValue({
    workspace_id: ownerWorkspaceId,
    member_id: ownerMemberId,
    csrf_token: "csrf-owner-with-sufficient-length",
  });
  render(<EnterPage />);

  await user.type(await screen.findByLabelText("团队名称"), "C哥内容团队");
  await user.type(screen.getByLabelText("我的名称"), "小白");
  await user.click(screen.getByRole("button", { name: "创建团队并进入" }));

  await waitFor(() => {
    expect(onboardWorkspaceOwnerMock).toHaveBeenCalledWith(
      "C哥内容团队",
      "小白",
    );
  });
  expect(enterWorkspaceMock).not.toHaveBeenCalled();
  expect(sessionStorage.getItem("workspace_csrf")).toBe(
    "csrf-owner-with-sufficient-length",
  );
  expect(readWorkspaceSessionRecovery(localStorage)).toEqual({
    version: 1,
    workspaceId: ownerWorkspaceId,
    memberId: ownerMemberId,
    csrfToken: "csrf-owner-with-sufficient-length",
  });
  expect(locationAssignMock).toHaveBeenCalledWith(
    `/workspaces/${ownerWorkspaceId}`,
  );
});

test("keeps invite joining independent from owner onboarding", async () => {
  const user = userEvent.setup();
  enterWorkspaceMock.mockResolvedValue({
    workspace_id: editorWorkspaceId,
    member_id: editorMemberId,
    csrf_token: "csrf-editor-with-sufficient-length",
  });
  render(<EnterPage />);

  await user.click(
    await screen.findByRole("button", { name: "加入团队", pressed: false }),
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
  expect(sessionStorage.getItem("workspace_csrf")).toBe(
    "csrf-editor-with-sufficient-length",
  );
  expect(readWorkspaceSessionRecovery(localStorage)).toEqual({
    version: 1,
    workspaceId: editorWorkspaceId,
    memberId: editorMemberId,
    csrfToken: "csrf-editor-with-sufficient-length",
  });
  expect(locationAssignMock).toHaveBeenCalledWith(
    `/workspaces/${editorWorkspaceId}`,
  );
});

test("returns a remembered valid member to the original workspace", async () => {
  writeWorkspaceSessionRecovery(localStorage, rememberedSession);
  loadWorkbenchContextMock.mockResolvedValue(rememberedContext);

  render(<EnterPage />);

  expect(screen.getByRole("status")).toHaveTextContent(
    "正在返回上次团队",
  );
  expect(
    screen.queryByRole("heading", { name: "进入你的运营工作区" }),
  ).not.toBeInTheDocument();
  await waitFor(() => {
    expect(locationAssignMock).toHaveBeenCalledWith(
      `/workspaces/${ownerWorkspaceId}`,
    );
  });
  expect(sessionStorage.getItem("workspace_csrf")).toBe(
    rememberedSession.csrfToken,
  );
});

test.each([401, 404])(
  "clears a remembered session after a %s response",
  async (status) => {
    writeWorkspaceSessionRecovery(localStorage, rememberedSession);
    sessionStorage.setItem("workspace_csrf", rememberedSession.csrfToken);
    loadWorkbenchContextMock.mockRejectedValue(new WorkbenchApiErrorMock(status));

    render(<EnterPage />);

    expect(
      await screen.findByRole("heading", { name: "进入你的运营工作区" }),
    ).toBeVisible();
    expect(readWorkspaceSessionRecovery(localStorage)).toBeNull();
    expect(sessionStorage.getItem("workspace_csrf")).toBeNull();
  },
);

test("rejects a remembered session whose member identity does not match", async () => {
  writeWorkspaceSessionRecovery(localStorage, rememberedSession);
  loadWorkbenchContextMock.mockResolvedValue({
    ...rememberedContext,
    member_id: editorMemberId,
  });

  render(<EnterPage />);

  expect(
    await screen.findByRole("heading", { name: "进入你的运营工作区" }),
  ).toBeVisible();
  expect(readWorkspaceSessionRecovery(localStorage)).toBeNull();
  expect(locationAssignMock).not.toHaveBeenCalled();
});

test("keeps recovery state and offers a retry after a connection failure", async () => {
  const user = userEvent.setup();
  writeWorkspaceSessionRecovery(localStorage, rememberedSession);
  loadWorkbenchContextMock
    .mockRejectedValueOnce(new TypeError("network unavailable"))
    .mockResolvedValueOnce(rememberedContext);

  render(<EnterPage />);

  const retry = await screen.findByRole("button", {
    name: "返回上次团队",
  });
  expect(readWorkspaceSessionRecovery(localStorage)).not.toBeNull();
  await user.click(retry);
  await waitFor(() => {
    expect(locationAssignMock).toHaveBeenCalledWith(
      `/workspaces/${ownerWorkspaceId}`,
    );
  });
});

test("locks the create mode while pending and restores it after a safe failure", async () => {
  const user = userEvent.setup();
  let rejectOnboarding: (reason?: unknown) => void = () => undefined;
  onboardWorkspaceOwnerMock.mockImplementation(
    () =>
      new Promise((_, reject) => {
        rejectOnboarding = reject;
      }),
  );
  render(<EnterPage />);

  await user.type(
    await screen.findByLabelText("团队名称"),
    "合成测试团队",
  );
  await user.type(screen.getByLabelText("我的名称"), "测试管理员");
  const submit = screen.getByRole("button", { name: "创建团队并进入" });
  const createMode = screen.getByRole("button", {
    name: "创建团队",
    pressed: true,
  });
  const joinMode = screen.getByRole("button", {
    name: "加入团队",
    pressed: false,
  });
  await user.click(submit);

  expect(submit).toBeDisabled();
  expect(createMode).toBeDisabled();
  expect(joinMode).toBeDisabled();
  await user.click(joinMode);
  expect(createMode).toHaveAttribute("aria-pressed", "true");
  expect(joinMode).toHaveAttribute("aria-pressed", "false");
  expect(screen.queryByLabelText("邀请码")).not.toBeInTheDocument();
  expect(onboardWorkspaceOwnerMock).toHaveBeenCalledTimes(1);

  rejectOnboarding(new Error("provider detail must stay hidden"));

  expect(
    await screen.findByRole("alert", {
      name: "创建失败，请稍后重试",
    }),
  ).toBeInTheDocument();
  expect(submit).toBeEnabled();
  expect(createMode).toBeEnabled();
  expect(joinMode).toBeEnabled();
});
