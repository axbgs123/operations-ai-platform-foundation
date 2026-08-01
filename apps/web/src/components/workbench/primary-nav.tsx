"use client";

import Link from "next/link";
import {
  useCallback,
  useSyncExternalStore,
  type ReactElement,
} from "react";

import {
  activeNavigationCategory,
  activeNavigationItem,
  defaultNavigationItem,
  visibleNavigationCategories,
  type WorkbenchNavigationCategory,
  type WorkbenchRole,
  workbenchHref,
} from "./navigation";
import { NavigationIcon } from "./navigation-icon";
import { readRecentNavigationPath } from "./navigation-preference";


function PrimaryCategoryLink({
  workspaceId,
  memberId,
  role,
  category,
  active,
  activeItemHref,
  onNavigate,
}: {
  workspaceId: string;
  memberId: string;
  role: WorkbenchRole;
  category: WorkbenchNavigationCategory;
  active: boolean;
  activeItemHref?: string;
  onNavigate: () => void;
}): ReactElement {
  const subscribe = useCallback((notify: () => void) => {
    window.addEventListener("storage", notify);
    return () => window.removeEventListener("storage", notify);
  }, []);
  const getSnapshot = useCallback(
    () => (
      readRecentNavigationPath(
        window.localStorage,
        memberId,
        category.id,
        role,
      ) ?? ""
    ),
    [category.id, memberId, role],
  );
  const recentPath = useSyncExternalStore(subscribe, getSnapshot, () => "");
  const href = active && activeItemHref !== undefined
    ? activeItemHref
    : (
        recentPath
        || defaultNavigationItem(category.id, role)?.href
        || category.defaultHref
      );

  return (
    <Link
      aria-current={active ? "page" : undefined}
      aria-label={category.label}
      className={`flex min-h-[54px] flex-col items-center justify-center gap-1 rounded-lg px-1 text-xs font-semibold ${
        active
          ? "bg-violet-100 text-[var(--brand)]"
          : "text-[var(--text-secondary)] hover:bg-white hover:text-[var(--text-primary)]"
      }`}
      href={workbenchHref(workspaceId, href)}
      onClick={onNavigate}
      title={category.navigationLabel}
    >
      <NavigationIcon name={category.icon} />
      <span>{category.label}</span>
    </Link>
  );
}

export function PrimaryNav({
  workspaceId,
  memberId,
  role,
  pathname,
  onNavigate,
  secondaryCollapsed,
  onToggleSecondary,
}: {
  workspaceId: string;
  memberId: string;
  role: WorkbenchRole;
  pathname: string;
  onNavigate: () => void;
  secondaryCollapsed: boolean;
  onToggleSecondary: () => void;
}): ReactElement {
  const activeCategory = activeNavigationCategory(pathname, workspaceId);
  const activeItem = activeNavigationItem(pathname, workspaceId);

  return (
    <nav
      aria-label="功能大类"
      className="flex h-full w-20 shrink-0 flex-col border-r bg-slate-50 px-2 py-3"
    >
      <p className="mb-4 text-center text-xs font-bold leading-4 text-[var(--text-primary)]">
        运营
        <br />
        工作台
      </p>
      {secondaryCollapsed ? (
        <button
          aria-label="展开功能列表"
          className="mb-3 min-h-9 rounded-lg border bg-white text-lg text-[var(--text-secondary)]"
          onClick={onToggleSecondary}
          type="button"
        >
          ›
        </button>
      ) : null}
      <ul className="space-y-1">
        {visibleNavigationCategories(role).map((category) => {
          const active = category.id === activeCategory?.id;
          return (
            <li key={category.id}>
              <PrimaryCategoryLink
                active={active}
                activeItemHref={active ? activeItem?.href : undefined}
                category={category}
                memberId={memberId}
                onNavigate={onNavigate}
                role={role}
                workspaceId={workspaceId}
              />
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
