"use client";

import Link from "next/link";
import type { ReactElement } from "react";

import {
  activeNavigationCategory,
  activeNavigationItem,
  defaultNavigationItem,
  type WorkbenchRole,
} from "./navigation";
import {
  buildWorkspaceHref,
  type WorkbenchScope,
} from "./scope-query";


export function Breadcrumbs({
  workspaceId,
  workspaceName,
  role,
  scope,
  pathname,
}: {
  workspaceId: string;
  workspaceName: string;
  role: WorkbenchRole;
  scope: WorkbenchScope;
  pathname: string;
}): ReactElement {
  const active = activeNavigationItem(pathname, workspaceId);
  const category = activeNavigationCategory(pathname, workspaceId);
  const categoryHref = (
    active?.allowedRoles.includes(role) ? active.href : undefined
  ) ?? (
    category ? defaultNavigationItem(category.id, role)?.href : undefined
  );

  return (
    <nav aria-label="面包屑" className="min-w-0 text-sm">
      <ol className="flex min-w-0 items-center gap-2">
        <li className="min-w-0">
          <Link
            className="block max-w-48 truncate text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            href={buildWorkspaceHref(workspaceId, "", scope)}
          >
            {workspaceName}
          </Link>
        </li>
        {active && category && categoryHref !== undefined ? (
          <>
            <li aria-hidden="true" className="text-slate-400">
              /
            </li>
            <li>
              <Link
                className="text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
                href={buildWorkspaceHref(workspaceId, categoryHref, scope)}
              >
                {category.label}
              </Link>
            </li>
            <li aria-hidden="true" className="text-slate-400">
              /
            </li>
            <li
              aria-current="page"
              className="truncate font-medium text-[var(--text-primary)]"
            >
              {active.label}
            </li>
          </>
        ) : null}
      </ol>
    </nav>
  );
}
