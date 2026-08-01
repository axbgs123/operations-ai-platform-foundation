"use client";

import {
  type KeyboardEvent,
  type ReactElement,
  type RefObject,
  useEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import Link from "next/link";

import {
  activeNavigationCategory,
  isNavigationItemActive,
  navigationCategory,
  visibleCategoryItems,
  visibleNavigationCategories,
  type WorkbenchNavigationCategoryId,
  type WorkbenchRole,
} from "./navigation";
import { NavigationIcon } from "./navigation-icon";
import {
  buildWorkspaceHref,
  type WorkbenchScope,
} from "./scope-query";


const FOCUSABLE =
  'a[href], button:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function MobileDrawer({
  open,
  onClose,
  returnFocusRef,
  workspaceId,
  role,
  pathname,
  scope,
}: {
  open: boolean;
  onClose: () => void;
  returnFocusRef: RefObject<HTMLButtonElement | null>;
  workspaceId: string;
  role: WorkbenchRole;
  pathname: string;
  scope: WorkbenchScope;
}): ReactElement | null {
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const backRef = useRef<HTMLButtonElement>(null);
  const categoryButtonRefs = useRef<
    Partial<Record<WorkbenchNavigationCategoryId, HTMLButtonElement | null>>
  >({});
  const navigationViewMountedRef = useRef(false);
  const workspaceRoot = `/workspaces/${workspaceId}`;
  const isWorkspaceOverview = (
    pathname === workspaceRoot || pathname === `${workspaceRoot}/`
  );
  const routeCategory = activeNavigationCategory(pathname, workspaceId);
  const visibleCategories = visibleNavigationCategories(role);
  const visibleRouteCategory = routeCategory && visibleCategories.some(
    (category) => category.id === routeCategory.id,
  )
    ? routeCategory
    : undefined;
  const lastSelectedCategoryRef = useRef<WorkbenchNavigationCategoryId | null>(
    isWorkspaceOverview ? null : (visibleRouteCategory?.id ?? null),
  );
  const [selectedCategoryId, setSelectedCategoryId] =
    useState<WorkbenchNavigationCategoryId | null>(
      isWorkspaceOverview ? null : (visibleRouteCategory?.id ?? null),
    );
  const selectedCategory = selectedCategoryId === null
    ? undefined
    : navigationCategory(selectedCategoryId);

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

  useEffect(() => {
    if (!open) return;
    if (!navigationViewMountedRef.current) {
      navigationViewMountedRef.current = true;
      return;
    }
    if (selectedCategoryId !== null) {
      backRef.current?.focus();
      return;
    }
    const lastCategoryId = lastSelectedCategoryRef.current;
    if (lastCategoryId !== null) {
      categoryButtonRefs.current[lastCategoryId]?.focus();
    }
  }, [open, selectedCategoryId]);

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
          <p className="font-semibold text-[var(--text-primary)]">
            {selectedCategory?.navigationLabel ?? "选择功能大类"}
          </p>
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
        {selectedCategory ? (
          <div>
            <button
              aria-label="返回全部分类"
              className="mx-4 mt-4 inline-flex min-h-10 items-center gap-2 rounded-lg px-2 text-sm font-semibold text-[var(--brand)] hover:bg-violet-50"
              onClick={() => setSelectedCategoryId(null)}
              ref={backRef}
              type="button"
            >
              <span aria-hidden="true">←</span>
              返回全部分类
            </button>
            <nav
              aria-label={`${selectedCategory.navigationLabel}功能`}
              className="px-4 py-3"
            >
              <ul className="space-y-2">
                {visibleCategoryItems(selectedCategory, role).map((item) => {
                  const active = isNavigationItemActive(
                    pathname,
                    workspaceId,
                    item,
                  );
                  return (
                    <li key={item.href}>
                      <Link
                        aria-current={active ? "page" : undefined}
                        className={`flex min-h-12 items-center justify-between rounded-xl border px-4 text-sm font-semibold ${
                          active
                            ? "border-violet-200 bg-violet-50 text-[var(--brand)]"
                            : "border-slate-200 bg-white text-[var(--text-primary)]"
                        }`}
                        href={buildWorkspaceHref(workspaceId, item.href, scope)}
                        onClick={onClose}
                      >
                        <span>{item.label}</span>
                        <span aria-hidden="true">›</span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </nav>
          </div>
        ) : (
          <nav aria-label="功能大类" className="px-4 py-4">
            <p className="mb-3 text-sm text-[var(--text-secondary)]">
              先选择大类，再进入具体功能。
            </p>
            <ul className="space-y-2">
              {visibleCategories.map((category) => (
                <li key={category.id}>
                  <button
                    aria-label={category.label}
                    className="flex min-h-14 w-full items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 text-left hover:border-violet-200 hover:bg-violet-50"
                    onClick={() => {
                      lastSelectedCategoryRef.current = category.id;
                      setSelectedCategoryId(category.id);
                    }}
                    ref={(element) => {
                      categoryButtonRefs.current[category.id] = element;
                    }}
                    type="button"
                  >
                    <span className="text-[var(--brand)]">
                      <NavigationIcon name={category.icon} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <strong className="block text-sm text-[var(--text-primary)]">
                        {category.label}
                      </strong>
                      <span className="block text-xs text-[var(--text-secondary)]">
                        {category.navigationLabel}
                      </span>
                    </span>
                    <span aria-hidden="true" className="text-slate-400">›</span>
                  </button>
                </li>
              ))}
            </ul>
          </nav>
        )}
      </div>
    </div>,
    document.body,
  );
}
