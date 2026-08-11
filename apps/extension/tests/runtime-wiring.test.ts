import { describe, expect, it, vi } from "vitest";

import { createBackgroundMessageHandler, createCaptureCoordinator, createCommandListener } from "../src/background";
import { createContentMessageHandler, fullPageFailureDisclosure } from "../src/content";
import { armAndStartSafeCapture } from "../src/popup/main";
import { parseRuntimeMessage } from "../src/runtime/messages";

const supportedTab = {
  id: 7,
  windowId: 3,
  url: "https://creator.douyin.com/creator-micro/content/manage",
};

const captureContext = {
  platform: "douyin" as const,
  pageVersion: "douyin-visible-tab-v1",
  pageSignature: "douyin:fixture",
};

const armMessage = {
  type: "START_SAFE_CAPTURE" as const,
  tabId: 7,
  armGeneration: 1,
  ...captureContext,
};

const storedBinding = {
  serverOrigin: "https://ops.example.com",
  webOrigin: "https://app.ops.example.com",
  workspaceId: "00000000-0000-0000-0000-000000000001",
  workspaceName: "不应发送到内容脚本",
  memberDisplayName: "不应发送到内容脚本",
  accessToken: "short-lived-token",
  expiresAt: "2026-08-10T09:00:00Z",
  providerMode: "mock" as const,
  region: null,
};

describe("extension runtime message boundary", () => {
  it("discloses the original stitch reason when every full-page prefix is unusable", () => {
    expect(fullPageFailureDisclosure({
      slices: [{}, {}, {}],
      stopReason: "bottom",
    }, "pixel-limit")).toEqual({
      dataUrl: null,
      complete: false,
      stopReason: "pixel-limit",
      sliceCount: 3,
    });
  });
  it("uses the command-provided tab to start the same full-page coordinator", async () => {
    const startCapture = vi.fn().mockResolvedValue(undefined);
    const commandListener = createCommandListener({ startCapture, cancel: vi.fn() });

    await commandListener("capture-full-page", supportedTab);

    expect(startCapture).toHaveBeenCalledWith("full-page", supportedTab);
  });
  it("clears an armed full-page coordinator session on cancellation", async () => {
    const endFullPageCapture = vi.fn().mockResolvedValue({ ok: true });
    const coordinator = createCaptureCoordinator({
      getPageStatus: vi.fn().mockResolvedValue({
        supported: true,
        ...captureContext,
        url: supportedTab.url,
        viewport: { width: 100, height: 100, devicePixelRatio: 1 },
        scrollY: 0,
      }),
      arm: vi.fn().mockResolvedValue({ ok: true }),
      startContent: vi.fn().mockResolvedValue({ ok: true }),
      endFullPageCapture,
      uuid: () => "full-page-session",
    });

    await coordinator.startCapture("full-page", supportedTab);
    await coordinator.cancel("overlay-cancelled");
    await coordinator.cancel("again");

    expect(endFullPageCapture).toHaveBeenCalledOnce();
    expect(endFullPageCapture).toHaveBeenCalledWith(7, "full-page-session");
  });

  it("ends the exact full-page session when content startup throws", async () => {
    const endFullPageCapture = vi.fn().mockResolvedValue({ ok: true });
    const coordinator = createCaptureCoordinator({
      getPageStatus: vi.fn().mockResolvedValue({
        supported: true,
        ...captureContext,
        url: supportedTab.url,
        viewport: { width: 100, height: 100, devicePixelRatio: 1 },
        scrollY: 0,
      }),
      arm: vi.fn().mockResolvedValue({ ok: true }),
      startContent: vi.fn().mockRejectedValue(new Error("content-script-gone")),
      endFullPageCapture,
      uuid: () => "throwing-session",
    });

    await expect(coordinator.startCapture("full-page", supportedTab)).rejects.toThrow("content-script-gone");
    expect(endFullPageCapture).toHaveBeenCalledOnce();
    expect(endFullPageCapture).toHaveBeenCalledWith(7, "throwing-session");
    await coordinator.cancel("test-complete");
    expect(endFullPageCapture).toHaveBeenCalledOnce();
  });
  it("notifies the coordinator when an exact full-page END clears the armed session", async () => {
    const finishCapture = vi.fn();
    const handler = createBackgroundMessageHandler({
      queryActiveTab: vi.fn().mockResolvedValue(supportedTab),
      captureVisibleTab: vi.fn(),
      captureCoordinator: { startCapture: vi.fn(), cancel: vi.fn(), finishCapture },
    });
    const arm = {
      type: "ARM_FULL_PAGE_CAPTURE" as const,
      tabId: 7,
      armGeneration: 1,
      captureSessionId: "ending-session",
      ...captureContext,
      url: supportedTab.url,
      viewport: { width: 100, height: 100, devicePixelRatio: 1 },
      scrollY: 0,
    };
    await handler(arm, {});
    await expect(handler(
      { type: "END_FULL_PAGE_CAPTURE", captureSessionId: "ending-session" },
      { tab: supportedTab },
    )).resolves.toEqual({ ok: true });
    expect(finishCapture).toHaveBeenCalledWith(7, "ending-session");
  });
  it("accepts only exact, typed capture messages", () => {
    expect(parseRuntimeMessage({ type: "GET_PAGE_STATUS" })).toEqual({ type: "GET_PAGE_STATUS" });
    expect(parseRuntimeMessage(armMessage)).toEqual(armMessage);
    expect(parseRuntimeMessage({ type: "CAPTURE_VISIBLE_TAB", pageSignature: "douyin:fixture" })).toEqual({
      type: "CAPTURE_VISIBLE_TAB",
      pageSignature: "douyin:fixture",
    });
    expect(parseRuntimeMessage({ type: "OPEN_REVIEW", url: "https://app.example/review" })).toEqual({
      type: "OPEN_REVIEW",
      url: "https://app.example/review",
    });
    expect(parseRuntimeMessage({ type: "GET_CAPTURE_BINDING", ...captureContext })).toEqual({
      type: "GET_CAPTURE_BINDING",
      ...captureContext,
    });
    expect(parseRuntimeMessage({ type: "GET_CAPTURE_BINDING", captureSessionId: "session-1", ...captureContext })).toEqual({
      type: "GET_CAPTURE_BINDING",
      captureSessionId: "session-1",
      ...captureContext,
    });
    expect(parseRuntimeMessage({ type: "GET_SESSION_BINDING" })).toEqual({ type: "GET_SESSION_BINDING" });
    expect(parseRuntimeMessage({ type: "UNLINK_SESSION" })).toEqual({ type: "UNLINK_SESSION" });

    expect(parseRuntimeMessage({ type: "CAPTURE_VISIBLE_TAB", pageSignature: "", token: "secret" })).toBeNull();
    expect(parseRuntimeMessage({ ...armMessage, tabId: -1 })).toBeNull();
    expect(parseRuntimeMessage({ ...armMessage, platform: "unknown" })).toBeNull();
    expect(parseRuntimeMessage({ type: "UNKNOWN" })).toBeNull();
  });

  it("keeps popup session renewal and unlink in the background-only runtime boundary", async () => {
    const binding = { ...storedBinding, expiresAt: "2030-01-01T08:00:00Z" };
    const ensureSessionBinding = vi.fn().mockResolvedValue(binding);
    const unlinkSession = vi.fn().mockResolvedValue(undefined);
    const handler = createBackgroundMessageHandler({
      queryActiveTab: vi.fn(), captureVisibleTab: vi.fn(), ensureSessionBinding, unlinkSession,
    });

    await expect(handler({ type: "GET_SESSION_BINDING" }, {})).resolves.toEqual({ ok: true, binding });
    await expect(handler({ type: "UNLINK_SESSION" }, {})).resolves.toEqual({ ok: true });
    await expect(handler({ type: "GET_SESSION_BINDING" }, { tab: supportedTab })).resolves.toEqual({ ok: false, error: "unsupported-message" });
    expect(ensureSessionBinding).toHaveBeenCalledOnce();
    expect(unlinkSession).toHaveBeenCalledOnce();
  });

  it("preserves a registered device when capture binding renewal is temporarily unavailable", async () => {
    const clearSessionBinding = vi.fn().mockResolvedValue(undefined);
    const unlinkSession = vi.fn().mockResolvedValue(undefined);
    const handler = createBackgroundMessageHandler({
      queryActiveTab: vi.fn().mockResolvedValue(supportedTab),
      captureVisibleTab: vi.fn(),
      loadBinding: vi.fn().mockRejectedValue(Object.assign(new Error("session-unavailable"), {
        code: "session-unavailable",
      })),
      clearSessionBinding,
      unlinkSession,
    });
    await handler(armMessage, {});

    await expect(
      handler({ type: "GET_CAPTURE_BINDING", ...captureContext }, { tab: supportedTab }),
    ).resolves.toEqual({ ok: false, error: "session-unavailable" });
    expect(clearSessionBinding).not.toHaveBeenCalled();
    expect(unlinkSession).not.toHaveBeenCalled();
  });

  it("returns only the minimum current capture binding to the armed active supported sender", async () => {
    const loadBinding = vi.fn().mockResolvedValue(storedBinding);
    const handler = createBackgroundMessageHandler({
      queryActiveTab: vi.fn().mockResolvedValue(supportedTab),
      captureVisibleTab: vi.fn(),
      loadBinding,
      now: () => Date.parse("2026-08-10T08:00:00Z"),
    });
    await handler(armMessage, {});

    await expect(
      handler({ type: "GET_CAPTURE_BINDING", ...captureContext }, { tab: supportedTab }),
    ).resolves.toEqual({
      ok: true,
      binding: {
        serverOrigin: storedBinding.serverOrigin,
        webOrigin: storedBinding.webOrigin,
        workspaceId: storedBinding.workspaceId,
        accessToken: storedBinding.accessToken,
        expiresAt: storedBinding.expiresAt,
        providerMode: storedBinding.providerMode,
      },
    });
    expect(loadBinding).toHaveBeenCalledOnce();
  });

  it("rejects binding reads from unarmed, inactive, unsupported, drifted, expired, or revoked senders", async () => {
    let active = supportedTab;
    let binding: typeof storedBinding | null = storedBinding;
    const clearSessionBinding = vi.fn(async () => { binding = null; });
    const handler = createBackgroundMessageHandler({
      queryActiveTab: vi.fn(async () => active),
      captureVisibleTab: vi.fn(),
      loadBinding: vi.fn(async () => binding),
      clearSessionBinding,
      now: () => Date.parse("2026-08-10T08:00:00Z"),
    });
    const read = { type: "GET_CAPTURE_BINDING" as const, ...captureContext };

    await expect(handler(read, { tab: supportedTab })).resolves.toEqual({ ok: false, error: "capture-not-armed" });
    await handler(armMessage, {});
    active = { ...supportedTab, id: 8 };
    await expect(handler(read, { tab: supportedTab })).resolves.toEqual({ ok: false, error: "inactive-or-unsupported-tab" });
    active = supportedTab;
    await handler(armMessage, {});
    await expect(handler({ ...read, pageSignature: "douyin:drifted" }, { tab: supportedTab })).resolves.toEqual({ ok: false, error: "capture-context-mismatch" });
    await handler(armMessage, {});
    binding = { ...storedBinding, expiresAt: "2026-08-10T07:59:59Z" };
    await expect(handler(read, { tab: supportedTab })).resolves.toEqual({ ok: false, error: "rebind-required" });
    expect(clearSessionBinding).toHaveBeenCalledOnce();
    await handler(armMessage, {});
    await expect(handler(read, { tab: supportedTab })).resolves.toEqual({ ok: false, error: "rebind-required" });
    await expect(handler(read, { tab: { ...supportedTab, url: "https://example.com" } })).resolves.toEqual({ ok: false, error: "inactive-or-unsupported-tab" });
  });

  it("captures only once after the popup arms the active supported tab", async () => {
    const captureVisibleTab = vi.fn().mockResolvedValue("data:image/png;base64,SAFE");
    const handler = createBackgroundMessageHandler({
      queryActiveTab: vi.fn().mockResolvedValue(supportedTab),
      captureVisibleTab,
      now: () => 1000,
    });

    await expect(handler(armMessage, {})).resolves.toEqual({ ok: true });
    await expect(
      handler(
        { type: "CAPTURE_VISIBLE_TAB", pageSignature: "douyin:fixture" },
        { tab: supportedTab },
      ),
    ).resolves.toEqual({ ok: true, dataUrl: "data:image/png;base64,SAFE" });
    expect(captureVisibleTab).toHaveBeenCalledWith(3, { format: "png" });

    await expect(
      handler(
        { type: "CAPTURE_VISIBLE_TAB", pageSignature: "douyin:fixture" },
        { tab: supportedTab },
      ),
    ).resolves.toEqual({ ok: false, error: "capture-not-armed" });
    expect(captureVisibleTab).toHaveBeenCalledTimes(1);
  });

  it("rejects inactive, unsupported, expired, and non-tab capture senders", async () => {
    const captureVisibleTab = vi.fn();
    let now = 1000;
    const queryActiveTab = vi.fn().mockResolvedValue(supportedTab);
    const handler = createBackgroundMessageHandler({
      queryActiveTab,
      captureVisibleTab,
      now: () => now,
    });

    await handler(armMessage, {});
    queryActiveTab.mockResolvedValueOnce({ ...supportedTab, id: 8 });
    await expect(
      handler({ type: "CAPTURE_VISIBLE_TAB", pageSignature: "douyin:fixture" }, { tab: supportedTab }),
    ).resolves.toEqual({ ok: false, error: "inactive-or-unsupported-tab" });

    await handler(armMessage, {});
    queryActiveTab.mockResolvedValueOnce({
      ...supportedTab,
      url: "https://creator.xiaohongshu.com/publish/publish-manage",
    });
    await expect(
      handler({ type: "CAPTURE_VISIBLE_TAB", pageSignature: "douyin:fixture" }, { tab: supportedTab }),
    ).resolves.toEqual({ ok: false, error: "inactive-or-unsupported-tab" });

    queryActiveTab.mockResolvedValue(supportedTab);
    await handler(armMessage, {});
    now = 32_000;
    await expect(
      handler({ type: "CAPTURE_VISIBLE_TAB", pageSignature: "douyin:fixture" }, { tab: supportedTab }),
    ).resolves.toEqual({ ok: false, error: "capture-not-armed" });

    await expect(
      handler({ type: "CAPTURE_VISIBLE_TAB", pageSignature: "douyin:fixture" }, {}),
    ).resolves.toEqual({ ok: false, error: "inactive-or-unsupported-tab" });
    expect(captureVisibleTab).not.toHaveBeenCalled();
  });

  it("binds the one-time arm to platform, page version, and page signature", async () => {
    const captureVisibleTab = vi.fn().mockResolvedValue("data:image/png;base64,SAFE");
    let active = supportedTab;
    const handler = createBackgroundMessageHandler({
      queryActiveTab: vi.fn(async () => active),
      captureVisibleTab,
    });
    await expect(handler(armMessage, {})).resolves.toEqual({ ok: true });
    await expect(
      handler(
        { type: "CAPTURE_VISIBLE_TAB", pageSignature: "douyin:different" },
        { tab: supportedTab },
      ),
    ).resolves.toEqual({ ok: false, error: "capture-context-mismatch" });
    expect(captureVisibleTab).not.toHaveBeenCalled();

    await expect(handler(armMessage, {})).resolves.toEqual({ ok: true });
    active = { ...supportedTab, url: `${supportedTab.url}/another-supported-view` };
    await expect(
      handler(
        { type: "CAPTURE_VISIBLE_TAB", pageSignature: "douyin:fixture" },
        { tab: active },
      ),
    ).resolves.toEqual({ ok: false, error: "capture-context-mismatch" });
    expect(captureVisibleTab).not.toHaveBeenCalled();

    active = supportedTab;
    await expect(
      handler({ ...armMessage, platform: "xiaohongshu" }, {}),
    ).resolves.toEqual({ ok: false, error: "inactive-or-unsupported-tab" });
  });

  it("fences multi-slice captures by armed session, sender, sequence, and exact page metadata", async () => {
    const captureVisibleTab = vi.fn().mockResolvedValue("data:image/png;base64,SAFE");
    const handler = createBackgroundMessageHandler({
      queryActiveTab: vi.fn().mockResolvedValue(supportedTab),
      captureVisibleTab,
      now: () => 1_000,
    });
    const arm = {
      type: "ARM_FULL_PAGE_CAPTURE" as const,
      tabId: 7,
      armGeneration: 1,
      captureSessionId: "session-1",
      ...captureContext,
      url: supportedTab.url,
      viewport: { width: 100, height: 100, devicePixelRatio: 1 },
      scrollY: 420,
    };
    const slice = {
      type: "CAPTURE_FULL_PAGE_SLICE" as const,
      captureSessionId: "session-1",
      sequence: 0,
      ...captureContext,
      url: supportedTab.url,
      viewport: { width: 100, height: 100, devicePixelRatio: 1 },
      scrollY: 420,
    };
    expect(parseRuntimeMessage(arm)).toEqual(arm);
    expect(parseRuntimeMessage(slice)).toEqual(slice);
    await expect(handler(arm, {})).resolves.toEqual({ ok: true });
    await expect(handler(slice, { tab: supportedTab })).resolves.toEqual({ ok: true, dataUrl: "data:image/png;base64,SAFE" });
    await expect(handler({ ...slice, sequence: 2 }, { tab: supportedTab })).resolves.toEqual({ ok: false, error: "capture-sequence-mismatch" });
    await expect(handler({ ...slice, captureSessionId: "other", sequence: 1 }, { tab: supportedTab })).resolves.toEqual({ ok: false, error: "capture-session-mismatch" });
    await expect(handler({ ...slice, sequence: 1, viewport: { ...slice.viewport, devicePixelRatio: 2 } }, { tab: supportedTab }))
      .resolves.toEqual({ ok: false, error: "capture-context-mismatch" });
    await expect(handler({ ...slice, sequence: 1 }, { tab: { ...supportedTab, id: 8 } }))
      .resolves.toEqual({ ok: false, error: "inactive-or-unsupported-tab" });
    expect(captureVisibleTab).toHaveBeenCalledTimes(1);
  });

  it("binds full-page credentials to the exact capture session and rejects content-script arming", async () => {
    const handler = createBackgroundMessageHandler({
      queryActiveTab: vi.fn().mockResolvedValue(supportedTab),
      captureVisibleTab: vi.fn(),
      loadBinding: vi.fn().mockResolvedValue(storedBinding),
      now: () => Date.parse("2026-08-10T08:00:00Z"),
    });
    const fullArm = {
      type: "ARM_FULL_PAGE_CAPTURE" as const,
      tabId: 7,
      armGeneration: 1,
      captureSessionId: "session-bound",
      ...captureContext,
      url: supportedTab.url,
      viewport: { width: 100, height: 100, devicePixelRatio: 1 },
      scrollY: 0,
    };

    await expect(handler(fullArm, { tab: supportedTab })).resolves.toEqual({ ok: false, error: "unsupported-message" });
    await expect(handler(armMessage, { tab: supportedTab })).resolves.toEqual({ ok: false, error: "unsupported-message" });
    await expect(handler(fullArm, {})).resolves.toEqual({ ok: true });
    await expect(handler(
      { type: "GET_CAPTURE_BINDING", ...captureContext },
      { tab: supportedTab },
    )).resolves.toEqual({ ok: false, error: "capture-session-mismatch" });
    await expect(handler(
      { type: "GET_CAPTURE_BINDING", captureSessionId: "other", ...captureContext },
      { tab: supportedTab },
    )).resolves.toEqual({ ok: false, error: "capture-session-mismatch" });
    await expect(handler(
      { type: "GET_CAPTURE_BINDING", captureSessionId: "session-bound", ...captureContext },
      { tab: supportedTab },
    )).resolves.toMatchObject({ ok: true });
  });

  it("clears incompatible visible and full-page arm state", async () => {
    const captureVisibleTab = vi.fn().mockResolvedValue("data:image/png;base64,U0FGRQ==");
    const handler = createBackgroundMessageHandler({
      queryActiveTab: vi.fn().mockResolvedValue(supportedTab),
      captureVisibleTab,
      now: () => 1_000,
    });
    const fullArm = {
      type: "ARM_FULL_PAGE_CAPTURE" as const,
      tabId: 7,
      armGeneration: 2,
      captureSessionId: "full-replacement",
      ...captureContext,
      url: supportedTab.url,
      viewport: { width: 100, height: 100, devicePixelRatio: 1 },
      scrollY: 0,
    };
    await handler({ ...armMessage, armGeneration: 1 }, {});
    await handler(fullArm, {});
    await expect(handler(
      { type: "CAPTURE_VISIBLE_TAB", pageSignature: captureContext.pageSignature },
      { tab: supportedTab },
    )).resolves.toEqual({ ok: false, error: "capture-not-armed" });

    await handler({ ...armMessage, armGeneration: 3 }, {});
    await expect(handler(
      { type: "CAPTURE_FULL_PAGE_SLICE", captureSessionId: "full-replacement", sequence: 0, ...captureContext, url: supportedTab.url, viewport: fullArm.viewport, scrollY: 0 },
      { tab: supportedTab },
    )).resolves.toEqual({ ok: false, error: "capture-not-armed" });
    expect(captureVisibleTab).not.toHaveBeenCalled();
  });

  it("keeps the newest coordinator generation when an older content start fails late", async () => {
    let resolveOldStart!: (response: unknown) => void;
    const endFullPageCapture = vi.fn().mockResolvedValue({ ok: true });
    const startContent = vi.fn()
      .mockImplementationOnce(() => new Promise((resolve) => { resolveOldStart = resolve; }))
      .mockResolvedValueOnce({ ok: true });
    const ids = ["old-session", "new-session"];
    const coordinator = createCaptureCoordinator({
      getPageStatus: vi.fn().mockResolvedValue({
        supported: true,
        ...captureContext,
        url: supportedTab.url,
        viewport: { width: 100, height: 100, devicePixelRatio: 1 },
        scrollY: 0,
      }),
      arm: vi.fn().mockResolvedValue({ ok: true }),
      startContent,
      endFullPageCapture,
      uuid: () => ids.shift()!,
    });

    const oldStart = coordinator.startCapture("full-page", supportedTab);
    await vi.waitFor(() => expect(startContent).toHaveBeenCalledOnce());
    await coordinator.startCapture("full-page", supportedTab);
    resolveOldStart({ ok: false });
    await expect(oldStart).rejects.toThrow();
    await coordinator.cancel("test-complete");

    expect(endFullPageCapture).toHaveBeenCalledWith(7, "old-session");
    expect(endFullPageCapture).toHaveBeenCalledWith(7, "new-session");
  });

  it("does not start old content when an older arm completes after its replacement", async () => {
    let resolveOldArm!: (response: unknown) => void;
    const arm = vi.fn()
      .mockImplementationOnce(() => new Promise((resolve) => { resolveOldArm = resolve; }))
      .mockResolvedValueOnce({ ok: true });
    const startContent = vi.fn().mockResolvedValue({ ok: true });
    const ids = ["old-arm", "new-arm"];
    const coordinator = createCaptureCoordinator({
      getPageStatus: vi.fn().mockResolvedValue({
        supported: true,
        ...captureContext,
        url: supportedTab.url,
        viewport: { width: 100, height: 100, devicePixelRatio: 1 },
        scrollY: 0,
      }),
      arm,
      startContent,
      endFullPageCapture: vi.fn().mockResolvedValue({ ok: true }),
      uuid: () => ids.shift()!,
    });

    const oldStart = coordinator.startCapture("full-page", supportedTab);
    await vi.waitFor(() => expect(arm).toHaveBeenCalledOnce());
    await coordinator.startCapture("full-page", supportedTab);
    resolveOldArm({ ok: true });

    await expect(oldStart).rejects.toThrow("capture-replaced");
    expect(startContent).toHaveBeenCalledTimes(1);
    expect(startContent).toHaveBeenCalledWith(7, {
      type: "START_CAPTURE",
      mode: "full-page",
      captureSessionId: "new-arm",
    });
  });

  it("keeps the newest real full-page arm when an older active-tab lookup completes late", async () => {
    let resolveOldQuery!: (tab: typeof supportedTab) => void;
    let queryCount = 0;
    const queryActiveTab = vi.fn(() => {
      queryCount += 1;
      if (queryCount === 1) {
        return new Promise<typeof supportedTab>((resolve) => { resolveOldQuery = resolve; });
      }
      return Promise.resolve(supportedTab);
    });
    const ids = ["old-real-arm", "new-real-arm"];
    let handler!: ReturnType<typeof createBackgroundMessageHandler>;
    const coordinator = createCaptureCoordinator({
      getPageStatus: vi.fn().mockResolvedValue({
        supported: true,
        ...captureContext,
        url: supportedTab.url,
        viewport: { width: 100, height: 100, devicePixelRatio: 1 },
        scrollY: 0,
      }),
      arm: (message) => handler(message, {}),
      startContent: vi.fn().mockResolvedValue({ ok: true }),
      endFullPageCapture: (tabId, captureSessionId) => handler(
        { type: "END_FULL_PAGE_CAPTURE", captureSessionId },
        { tab: { id: tabId } },
      ),
      uuid: () => ids.shift()!,
    });
    handler = createBackgroundMessageHandler({
      queryActiveTab,
      captureVisibleTab: vi.fn(),
      now: () => 1_000,
      loadBinding: vi.fn().mockResolvedValue({
        ...storedBinding,
        expiresAt: "2030-01-01T00:00:00Z",
      }),
      captureCoordinator: coordinator,
    });

    const oldStart = coordinator.startCapture("full-page", supportedTab);
    await vi.waitFor(() => expect(queryActiveTab).toHaveBeenCalledOnce());
    await coordinator.startCapture("full-page", supportedTab);
    resolveOldQuery(supportedTab);
    await expect(oldStart).rejects.toThrow("capture-replaced");

    await expect(handler(
      { type: "GET_CAPTURE_BINDING", captureSessionId: "new-real-arm", ...captureContext },
      { tab: supportedTab },
    )).resolves.toMatchObject({ ok: true });
  });

  it("keeps a newer visible arm when an older full-page active-tab lookup completes late", async () => {
    let resolveOldQuery!: (tab: typeof supportedTab) => void;
    let queryCount = 0;
    const queryActiveTab = vi.fn(() => {
      queryCount += 1;
      if (queryCount === 1) {
        return new Promise<typeof supportedTab>((resolve) => { resolveOldQuery = resolve; });
      }
      return Promise.resolve(supportedTab);
    });
    let handler!: ReturnType<typeof createBackgroundMessageHandler>;
    const captureVisibleTab = vi.fn().mockResolvedValue("data:image/png;base64,U0FGRQ==");
    const coordinator = createCaptureCoordinator({
      getPageStatus: vi.fn().mockResolvedValue({
        supported: true,
        ...captureContext,
        url: supportedTab.url,
        viewport: { width: 100, height: 100, devicePixelRatio: 1 },
        scrollY: 0,
      }),
      arm: (message) => handler(message, {}),
      startContent: vi.fn().mockResolvedValue({ ok: true }),
      endFullPageCapture: (tabId, captureSessionId) => handler(
        { type: "END_FULL_PAGE_CAPTURE", captureSessionId },
        { tab: { id: tabId } },
      ),
      uuid: () => "old-full-page",
    });
    handler = createBackgroundMessageHandler({
      queryActiveTab,
      captureVisibleTab,
      now: () => 1_000,
      captureCoordinator: coordinator,
    });

    const oldStart = coordinator.startCapture("full-page", supportedTab);
    await vi.waitFor(() => expect(queryActiveTab).toHaveBeenCalledOnce());
    await coordinator.startCapture("visible", supportedTab);
    resolveOldQuery(supportedTab);
    await expect(oldStart).rejects.toThrow("capture-replaced");

    await expect(handler(
      { type: "CAPTURE_VISIBLE_TAB", pageSignature: captureContext.pageSignature },
      { tab: supportedTab },
    )).resolves.toEqual({ ok: true, dataUrl: "data:image/png;base64,U0FGRQ==" });
  });

  it("atomically reserves a full-page sequence and rejects a concurrent duplicate", async () => {
    let resolveCapture: ((value: string) => void) | undefined;
    const captureVisibleTab = vi.fn(() => new Promise<string>((resolve) => { resolveCapture = resolve; }));
    const handler = createBackgroundMessageHandler({ queryActiveTab: vi.fn().mockResolvedValue(supportedTab), captureVisibleTab, now: () => 1_000 });
    const arm = { type: "ARM_FULL_PAGE_CAPTURE" as const, tabId: 7, armGeneration: 1, captureSessionId: "session-1", ...captureContext, url: supportedTab.url, viewport: { width: 100, height: 100, devicePixelRatio: 1 }, scrollY: 420 };
    const slice = { type: "CAPTURE_FULL_PAGE_SLICE" as const, captureSessionId: "session-1", sequence: 0, ...captureContext, url: supportedTab.url, viewport: { width: 100, height: 100, devicePixelRatio: 1 }, scrollY: 420 };
    await handler(arm, {});
    const first = handler(slice, { tab: supportedTab });
    await vi.waitFor(() => expect(captureVisibleTab).toHaveBeenCalledOnce());
    await expect(handler(slice, { tab: supportedTab })).resolves.toEqual({ ok: false, error: "capture-in-progress" });
    expect(captureVisibleTab).toHaveBeenCalledOnce();
    resolveCapture?.("data:image/png;base64,SAFE");
    await expect(first).resolves.toEqual({ ok: true, dataUrl: "data:image/png;base64,SAFE" });
  });

  it("rejects a slice which finishes after the full-page deadline", async () => {
    let now = 1_000;
    const captureVisibleTab = vi.fn(async () => { now = 21_001; return "data:image/png;base64,LATE"; });
    const handler = createBackgroundMessageHandler({ queryActiveTab: vi.fn().mockResolvedValue(supportedTab), captureVisibleTab, now: () => now });
    const arm = { type: "ARM_FULL_PAGE_CAPTURE" as const, tabId: 7, armGeneration: 1, captureSessionId: "session-1", ...captureContext, url: supportedTab.url, viewport: { width: 100, height: 100, devicePixelRatio: 1 }, scrollY: 420 };
    const slice = { type: "CAPTURE_FULL_PAGE_SLICE" as const, captureSessionId: "session-1", sequence: 0, ...captureContext, url: supportedTab.url, viewport: { width: 100, height: 100, devicePixelRatio: 1 }, scrollY: 420 };
    await handler(arm, {});
    await expect(handler(slice, { tab: supportedTab })).resolves.toEqual({ ok: false, error: "capture-not-armed" });
  });

  it("does not let a late resolved old capture delete or advance its replacement session", async () => {
    let resolveOld: ((value: string) => void) | undefined;
    const captureVisibleTab = vi.fn()
      .mockImplementationOnce(() => new Promise<string>((resolve) => { resolveOld = resolve; }))
      .mockResolvedValueOnce("data:image/png;base64,NEW");
    const handler = createBackgroundMessageHandler({ queryActiveTab: vi.fn().mockResolvedValue(supportedTab), captureVisibleTab, now: () => 1_000 });
    const message = (captureSessionId: string) => ({ type: "CAPTURE_FULL_PAGE_SLICE" as const, captureSessionId, sequence: 0, ...captureContext, url: supportedTab.url, viewport: { width: 100, height: 100, devicePixelRatio: 1 }, scrollY: 420 });
    const arm = (captureSessionId: string, armGeneration: number) => ({ type: "ARM_FULL_PAGE_CAPTURE" as const, tabId: 7, armGeneration, captureSessionId, ...captureContext, url: supportedTab.url, viewport: { width: 100, height: 100, devicePixelRatio: 1 }, scrollY: 420 });
    await handler(arm("old", 1), {});
    const old = handler(message("old"), { tab: supportedTab });
    await vi.waitFor(() => expect(captureVisibleTab).toHaveBeenCalledOnce());
    await handler({ type: "END_FULL_PAGE_CAPTURE", captureSessionId: "old" }, { tab: supportedTab });
    await handler(arm("new", 2), {});
    resolveOld?.("data:image/png;base64,OLD");
    await expect(old).resolves.toEqual({ ok: false, error: "capture-not-armed" });
    await expect(handler(message("new"), { tab: supportedTab })).resolves.toEqual({ ok: true, dataUrl: "data:image/png;base64,NEW" });
  });

  it("does not let a late rejected old capture delete or advance its replacement session", async () => {
    let rejectOld: ((reason?: unknown) => void) | undefined;
    const captureVisibleTab = vi.fn()
      .mockImplementationOnce(() => new Promise<string>((_resolve, reject) => { rejectOld = reject; }))
      .mockResolvedValueOnce("data:image/png;base64,NEW");
    const handler = createBackgroundMessageHandler({ queryActiveTab: vi.fn().mockResolvedValue(supportedTab), captureVisibleTab, now: () => 1_000 });
    const message = (captureSessionId: string) => ({ type: "CAPTURE_FULL_PAGE_SLICE" as const, captureSessionId, sequence: 0, ...captureContext, url: supportedTab.url, viewport: { width: 100, height: 100, devicePixelRatio: 1 }, scrollY: 420 });
    const arm = (captureSessionId: string, armGeneration: number) => ({ type: "ARM_FULL_PAGE_CAPTURE" as const, tabId: 7, armGeneration, captureSessionId, ...captureContext, url: supportedTab.url, viewport: { width: 100, height: 100, devicePixelRatio: 1 }, scrollY: 420 });
    await handler(arm("old", 1), {});
    const old = handler(message("old"), { tab: supportedTab });
    await vi.waitFor(() => expect(captureVisibleTab).toHaveBeenCalledOnce());
    await handler({ type: "END_FULL_PAGE_CAPTURE", captureSessionId: "old" }, { tab: supportedTab });
    await handler(arm("new", 2), {});
    rejectOld?.(new Error("old failed"));
    await expect(old).resolves.toEqual({ ok: false, error: "capture-not-armed" });
    await expect(handler(message("new"), { tab: supportedTab })).resolves.toEqual({ ok: true, dataUrl: "data:image/png;base64,NEW" });
  });

  it("arms the active tab before asking its content script to start", async () => {
    const arm = vi.fn().mockResolvedValue({ ok: true });
    const startContent = vi.fn().mockResolvedValue({ ok: true });
    await expect(armAndStartSafeCapture(7, captureContext, arm, startContent)).resolves.toBeUndefined();
    expect(arm.mock.invocationCallOrder[0]).toBeLessThan(startContent.mock.invocationCallOrder[0]);
    expect(arm).toHaveBeenCalledWith(armMessage);
    expect(startContent).toHaveBeenCalledWith({ type: "START_SAFE_CAPTURE" });

    startContent.mockClear();
    await expect(
      armAndStartSafeCapture(7, captureContext, vi.fn().mockResolvedValue({ ok: false }), startContent),
    ).rejects.toThrow("capture-not-armed");
    expect(startContent).not.toHaveBeenCalled();

    await expect(
      armAndStartSafeCapture(
        7,
        captureContext,
        vi.fn().mockResolvedValue({ ok: true }),
        vi.fn().mockResolvedValue({ ok: false, error: "rebind-required" }),
      ),
    ).rejects.toThrow("rebind-required");
  });

  it("reports page status and mounts capture only for an exact explicit start message", async () => {
    const mount = vi.fn().mockResolvedValue(undefined);
    const handler = createContentMessageHandler({
      detect: () => ({
        supported: true,
        platform: "douyin",
        pageVersion: "douyin-visible-tab-v1",
        signature: "douyin:fixture",
        captureRegion: null,
        sensitiveRegions: [],
      }),
      startCapture: mount,
    });
    await expect(handler({ type: "GET_PAGE_STATUS" })).resolves.toEqual({
      supported: true,
      platform: "douyin",
      pageVersion: "douyin-visible-tab-v1",
      pageSignature: "douyin:fixture",
    });
    await expect(handler({ type: "START_SAFE_CAPTURE" })).resolves.toEqual({ ok: true });
    expect(mount).toHaveBeenCalledOnce();
    await expect(handler({ type: "START_SAFE_CAPTURE", extra: true })).resolves.toEqual({
      ok: false,
      error: "invalid-message",
    });
    expect(mount).toHaveBeenCalledOnce();
  });
});
