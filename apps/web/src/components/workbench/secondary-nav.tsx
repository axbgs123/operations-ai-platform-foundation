import Link from "next/link";
import type { ReactElement } from "react";

import {
  isNavigationItemActive,
  type WorkbenchNavigationCategory,
  type WorkbenchRole,
  visibleCategoryItems,
} from "./navigation";
import {
  buildWorkspaceHref,
  type WorkbenchScope,
} from "./scope-query";


export function SecondaryNav({
  category,
  workspaceId,
  role,
  pathname,
  scope = {},
  onNavigate,
  onCollapse,
}: {
  category: WorkbenchNavigationCategory;
  workspaceId: string;
  role: WorkbenchRole;
  pathname: string;
  scope?: WorkbenchScope;
  onNavigate: () => void;
  onCollapse: () => void;
}): ReactElement {
  return (
    <div className="h-full w-[184px] shrink-0 bg-white">
      <div className="flex min-h-14 items-center justify-between border-b px-3">
        <div className="min-w-0">
          <span className="block text-xs text-[var(--text-secondary)]">大类</span>
          <strong className="block truncate text-sm text-[var(--text-primary)]">
            {category.navigationLabel}
          </strong>
        </div>
        <button
          aria-label="收起功能列表"
          className="h-9 w-9 shrink-0 rounded-lg border bg-white text-[var(--text-secondary)]"
          onClick={onCollapse}
          type="button"
        >
          ‹
        </button>
      </div>
      <nav
        aria-label={`${category.navigationLabel}功能`}
        className="px-3 py-4"
      >
        <ul className="space-y-1">
          {visibleCategoryItems(category, role).map((item) => {
            const active = isNavigationItemActive(pathname, workspaceId, item);
            return (
              <li key={item.label}>
                <Link
                  aria-current={active ? "page" : undefined}
                  className={`flex min-h-10 items-center rounded-lg px-3 text-sm font-medium ${
                    active
                      ? "bg-violet-50 text-[var(--brand)]"
                      : "text-[var(--text-secondary)] hover:bg-slate-100 hover:text-[var(--text-primary)]"
                  }`}
                  href={buildWorkspaceHref(workspaceId, item.href, scope)}
                  onClick={onNavigate}
                >
                  {item.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </div>
  );
}
