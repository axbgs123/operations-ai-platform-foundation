"use client";

import {
  type KeyboardEvent,
  type ReactElement,
  type RefObject,
  useEffect,
  useRef,
} from "react";
import { createPortal } from "react-dom";

import type { WorkbenchRole } from "./navigation";
import { SidebarNav } from "./sidebar-nav";


const FOCUSABLE =
  'a[href], button:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function MobileDrawer({
  open,
  onClose,
  returnFocusRef,
  workspaceId,
  role,
  pathname,
}: {
  open: boolean;
  onClose: () => void;
  returnFocusRef: RefObject<HTMLButtonElement | null>;
  workspaceId: string;
  role: WorkbenchRole;
  pathname: string;
}): ReactElement | null {
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    const returnFocusElement = returnFocusRef.current;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();
    return () => {
      document.body.style.overflow = previousOverflow;
      returnFocusElement?.focus();
    };
  }, [open, returnFocusRef]);

  if (!open) return null;

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = Array.from(
      dialogRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [],
    );
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return createPortal(
    <div className="fixed inset-0 z-50 bg-slate-950/45">
      <div
        aria-label="主导航"
        aria-modal="true"
        className="h-full w-[min(88vw,320px)] overflow-y-auto bg-white shadow-2xl"
        onKeyDown={handleKeyDown}
        ref={dialogRef}
        role="dialog"
      >
        <div className="flex min-h-14 items-center justify-between border-b px-4">
          <p className="font-semibold text-[var(--text-primary)]">运营工作台</p>
          <button
            aria-label="关闭主导航"
            className="h-10 w-10 rounded-lg border text-xl"
            onClick={onClose}
            ref={closeRef}
            type="button"
          >
            ×
          </button>
        </div>
        <SidebarNav
          collapsed={false}
          onNavigate={onClose}
          pathname={pathname}
          role={role}
          workspaceId={workspaceId}
        />
      </div>
    </div>,
    document.body,
  );
}
