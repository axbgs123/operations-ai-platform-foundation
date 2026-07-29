"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  useCallback,
  type ReactElement,
  type ReactNode,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

import {
  loadWorkbenchContext,
  WorkbenchApiError,
  type WorkbenchContext,
} from "@/lib/workbench-api";

import { MobileDrawer } from "./mobile-drawer";
import { SidebarNav } from "./sidebar-nav";
import {
  buildWorkspaceHref,
  parseWorkbenchScope,
  readSidebarPreference,
  type SidebarPreference,
  type WorkbenchScope,
  writeSidebarPreference,
} from "./scope-query";
import { ErrorState, Skeleton } from "./ui";
import { WorkspaceTopbar } from "./workspace-topbar";


function useMobileViewport(): boolean {
  const [mobile, setMobile] = useState(() =>
    typeof window === "undefined"
      ? false
      : window.matchMedia("(max-width: 767px)").matches,
  );
  useEffect(() => {
    const query = window.matchMedia("(max-width: 767px)");
    const update = () => setMobile(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return mobile;
}

function useSidebarPreference(memberId: string): [
  SidebarPreference,
  (preference: SidebarPreference) => void,
] {
  const eventName = `operations-ai:sidebar-change:${memberId}`;
  const subscribe = useCallback(
    (notify: () => void) => {
      const handleStorage = (event: StorageEvent) => {
        if (event.key === `operations-ai:sidebar:${memberId}`) notify();
      };
      window.addEventListener("storage", handleStorage);
      window.addEventListener(eventName, notify);
      return () => {
        window.removeEventListener("storage", handleStorage);
        window.removeEventListener(eventName, notify);
      };
    },
    [eventName, memberId],
  );
  const getSnapshot = useCallback(
    () => readSidebarPreference(window.localStorage, memberId),
    [memberId],
  );
  const preference = useSyncExternalStore<SidebarPreference>(
    subscribe,
    getSnapshot,
    (): SidebarPreference => "expanded",
  );
  const setPreference = useCallback(
    (next: SidebarPreference) => {
      writeSidebarPreference(window.localStorage, memberId, next);
      window.dispatchEvent(new Event(eventName));
    },
    [eventName, memberId],
  );
  return [preference, setPreference];
}

export function WorkspaceShell({
  context,
  children,
}: {
  context: WorkbenchContext;
  children: ReactNode;
}): ReactElement {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const router = useRouter();
  const isMobile = useMobileViewport();
  const navigationTriggerRef = useRef<HTMLButtonElement>(null);
  const [drawerPathname, setDrawerPathname] = useState<string | null>(null);
  const [sidebarPreference, setSidebarPreference] = useSidebarPreference(
    context.member_id,
  );
  const scope = parseWorkbenchScope(searchParams, context.accounts);
  const mobileOpen = drawerPathname === pathname;

  function changeScope(nextScope: WorkbenchScope) {
    router.replace(
      buildWorkspaceHref(context.workspace_id, pathname, nextScope),
    );
  }

  function toggleSidebar() {
    const next = sidebarPreference === "expanded"
      ? "collapsed"
      : "expanded";
    setSidebarPreference(next);
  }

  const collapsed = sidebarPreference === "collapsed";
  return (
    <div className="min-h-screen bg-[var(--canvas)] text-[var(--text-primary)]">
      <Link
        className="sr-only z-[70] rounded bg-white px-3 py-2 focus:not-sr-only focus:fixed focus:left-3 focus:top-3"
        href="#main-content"
      >
        跳转到主内容
      </Link>
      {!isMobile ? (
        <aside
          className={`fixed inset-y-0 left-0 z-30 overflow-y-auto border-r bg-white ${
            collapsed ? "w-[72px]" : "w-[240px]"
          }`}
          data-width={collapsed ? "72" : "240"}
        >
          <div className="flex min-h-14 items-center justify-between border-b px-3">
            <span className={collapsed ? "sr-only" : "font-semibold"}>
              运营工作台
            </span>
            <button
              aria-label={collapsed ? "展开侧边栏" : "折叠侧边栏"}
              className="h-9 w-9 rounded-lg border bg-white"
              onClick={toggleSidebar}
              type="button"
            >
              {collapsed ? "»" : "«"}
            </button>
          </div>
          <SidebarNav
            collapsed={collapsed}
            onNavigate={() => undefined}
            pathname={pathname}
            role={context.role}
            workspaceId={context.workspace_id}
          />
        </aside>
      ) : null}
      <div
        className={!isMobile ? (collapsed ? "pl-[72px]" : "pl-[240px]") : ""}
        data-testid="workspace-shell-background"
        inert={mobileOpen ? true : undefined}
      >
        <WorkspaceTopbar
          context={context}
          isMobile={isMobile}
          navigationTriggerRef={navigationTriggerRef}
          onOpenNavigation={() => setDrawerPathname(pathname)}
          onScopeChange={changeScope}
          pathname={pathname}
          scope={scope}
        />
        <main className="min-h-[calc(100vh-56px)] p-4 sm:p-6" id="main-content">
          {children}
        </main>
      </div>
      <MobileDrawer
        onClose={() => setDrawerPathname(null)}
        open={isMobile && mobileOpen}
        pathname={pathname}
        returnFocusRef={navigationTriggerRef}
        role={context.role}
        workspaceId={context.workspace_id}
      />
    </div>
  );
}

type LoaderState =
  | { status: "loading" }
  | { status: "ready"; context: WorkbenchContext }
  | { status: "session_expired" }
  | { status: "failed" };

export function WorkspaceShellLoader({
  workspaceId,
  children,
}: {
  workspaceId: string;
  children: ReactNode;
}): ReactElement {
  return (
    <WorkspaceShellContextLoader key={workspaceId} workspaceId={workspaceId}>
      {children}
    </WorkspaceShellContextLoader>
  );
}

function WorkspaceShellContextLoader({
  workspaceId,
  children,
}: {
  workspaceId: string;
  children: ReactNode;
}): ReactElement {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<LoaderState>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    loadWorkbenchContext(workspaceId, controller.signal)
      .then((context) => setState({ status: "ready", context }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState(
          error instanceof WorkbenchApiError && error.status === 401
            ? { status: "session_expired" }
            : { status: "failed" },
        );
      });
    return () => controller.abort();
  }, [attempt, workspaceId]);

  if (state.status === "loading") {
    return (
      <main className="min-h-screen bg-[var(--canvas)] p-6">
        <Skeleton label="正在加载工作区" />
      </main>
    );
  }
  if (state.status === "session_expired") {
    return (
      <main className="min-h-screen bg-[var(--canvas)] p-6">
        <ErrorState
          description="当前会话已过期或被撤销，请重新使用邀请码进入。"
          retryAction={<Link href="/enter">重新进入工作区</Link>}
          title="会话已失效"
        />
      </main>
    );
  }
  if (state.status === "failed") {
    return (
      <main className="min-h-screen bg-[var(--canvas)] p-6">
        <ErrorState
          description="无法安全加载工作区上下文，请检查网络后重试。"
          retryAction={
            <button
              className="rounded-lg bg-[var(--brand)] px-4 py-2 text-sm font-semibold text-white"
              onClick={() => {
                setState({ status: "loading" });
                setAttempt((value) => value + 1);
              }}
              type="button"
            >
              重新加载
            </button>
          }
          title="工作区加载失败"
        />
      </main>
    );
  }
  return (
    <WorkspaceShell context={state.context}>{children}</WorkspaceShell>
  );
}
