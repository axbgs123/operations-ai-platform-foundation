import Link from "next/link";
import type { ReactElement } from "react";

import { activeNavigationItem, workbenchHref } from "./navigation";


export function Breadcrumbs({
  workspaceId,
  workspaceName,
  pathname,
}: {
  workspaceId: string;
  workspaceName: string;
  pathname: string;
}): ReactElement {
  const active = activeNavigationItem(pathname, workspaceId);
  return (
    <nav aria-label="面包屑" className="min-w-0 text-sm">
      <ol className="flex min-w-0 items-center gap-2">
        <li className="min-w-0">
          <Link
            className="block max-w-48 truncate text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
            href={workbenchHref(workspaceId, "")}
          >
            {workspaceName}
          </Link>
        </li>
        {active ? (
          <>
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
