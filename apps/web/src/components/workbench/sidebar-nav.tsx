"use client";

import Link from "next/link";
import type { ReactElement } from "react";

import {
  isNavigationItemActive,
  type WorkbenchRole,
  WORKBENCH_NAV_GROUPS,
  workbenchHref,
} from "./navigation";


function NavigationIcon({ name }: { name: string }): ReactElement {
  return (
    <svg
      aria-hidden="true"
      className="h-5 w-5 shrink-0"
      fill="none"
      viewBox="0 0 24 24"
    >
      <rect
        height="14"
        rx="3"
        stroke="currentColor"
        strokeWidth="1.8"
        width="14"
        x="5"
        y="5"
      />
      <path
        d={name.length % 2 === 0 ? "M8 12h8M12 8v8" : "M8 9h8M8 15h5"}
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth="1.8"
      />
    </svg>
  );
}

export function SidebarNav({
  workspaceId,
  role,
  pathname,
  collapsed,
  onNavigate,
}: {
  workspaceId: string;
  role: WorkbenchRole;
  pathname: string;
  collapsed: boolean;
  onNavigate: () => void;
}): ReactElement {
  return (
    <nav aria-label="主导航" className="space-y-5 px-3 py-4">
      {WORKBENCH_NAV_GROUPS.map((group) => {
        const items = group.items.filter((item) =>
          item.allowedRoles.includes(role),
        );
        if (items.length === 0) return null;
        return (
          <section aria-label={group.label} key={group.label}>
            <h2
              className={
                collapsed
                  ? "sr-only"
                  : "mb-2 px-2 text-xs font-semibold uppercase tracking-wide text-[var(--text-secondary)]"
              }
            >
              {group.label}
            </h2>
            <ul className="space-y-1">
              {items.map((item) => {
                const active = isNavigationItemActive(
                  pathname,
                  workspaceId,
                  item,
                );
                const tooltipId = `nav-tooltip-${item.icon}`;
                return (
                  <li className="group relative" key={item.label}>
                    <Link
                      aria-current={active ? "page" : undefined}
                      aria-describedby={collapsed ? tooltipId : undefined}
                      aria-label={item.label}
                      className={`flex min-h-10 items-center gap-3 rounded-lg px-3 text-sm font-medium ${
                        active
                          ? "bg-violet-50 text-[var(--brand)]"
                          : "text-[var(--text-secondary)] hover:bg-slate-100 hover:text-[var(--text-primary)]"
                      }`}
                      href={workbenchHref(workspaceId, item.href)}
                      onClick={onNavigate}
                    >
                      <NavigationIcon name={item.icon} />
                      <span className={collapsed ? "sr-only" : ""}>
                        {item.label}
                      </span>
                    </Link>
                    {collapsed ? (
                      <span
                        className="pointer-events-none absolute left-full top-1/2 z-50 ml-2 -translate-y-1/2 whitespace-nowrap rounded bg-slate-900 px-2 py-1 text-xs text-white opacity-0 group-focus-within:opacity-100 group-hover:opacity-100"
                        id={tooltipId}
                        role="tooltip"
                      >
                        {item.label}
                      </span>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
    </nav>
  );
}
