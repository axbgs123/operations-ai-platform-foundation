"use client";

import {
  KeyboardEvent,
  ReactElement,
  ReactNode,
  useId,
} from "react";

import { useOptionalExperiencePreferences } from "./experience-preferences-context";
import type { ModeAwareCopy } from "./operator-copy-catalog";

export type StatusTone =
  | "neutral"
  | "info"
  | "success"
  | "warning"
  | "danger";

const statusToneClasses: Record<StatusTone, string> = {
  neutral: "border-slate-200 bg-slate-100 text-slate-700",
  info: "border-blue-200 bg-blue-50 text-blue-800",
  success: "border-emerald-200 bg-emerald-50 text-emerald-800",
  warning: "border-amber-200 bg-amber-50 text-amber-900",
  danger: "border-red-200 bg-red-50 text-red-800",
};

export type DisplayCopy = string | ModeAwareCopy;

export function DisplayText({ copy }: { copy: DisplayCopy }): ReactElement {
  const preferences = useOptionalExperiencePreferences();
  const copyMode = preferences?.copyMode ?? "simple";
  return <>{typeof copy === "string" ? copy : copy[copyMode]}</>;
}

export function StatusBadge({
  tone,
  children,
}: {
  tone: StatusTone;
  children: ReactNode;
}): ReactElement {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-semibold ${statusToneClasses[tone]}`}
      data-tone={tone}
    >
      {children}
    </span>
  );
}

export function PageHeader({
  title,
  description,
  primaryAction,
  secondaryActions,
}: {
  title: string;
  description?: DisplayCopy;
  primaryAction?: ReactNode;
  secondaryActions?: ReactNode;
}): ReactElement {
  const hasActions = Boolean(primaryAction || secondaryActions);

  return (
    <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight text-[var(--text-primary)]">
          {title}
        </h1>
        {description ? (
          <p className="mt-2 max-w-3xl text-sm leading-6 text-[var(--text-secondary)]">
            <DisplayText copy={description} />
          </p>
        ) : null}
      </div>
      {hasActions ? (
        <div
          aria-label="页面操作"
          className="flex shrink-0 flex-wrap items-center gap-2"
          role="group"
        >
          {secondaryActions}
          {primaryAction}
        </div>
      ) : null}
    </header>
  );
}

export function Panel({
  title,
  description,
  children,
}: {
  title: string;
  description?: DisplayCopy;
  children: ReactNode;
}): ReactElement {
  const headingId = useId();

  return (
    <section
      aria-labelledby={headingId}
      className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5"
    >
      <div className="mb-4">
        <h2
          className="text-lg font-semibold text-[var(--text-primary)]"
          id={headingId}
        >
          {title}
        </h2>
        {description ? (
          <p className="mt-1 text-sm text-[var(--text-secondary)]">
            <DisplayText copy={description} />
          </p>
        ) : null}
      </div>
      {children}
    </section>
  );
}

function StateMessage({
  title,
  description,
  action,
  role,
  tone,
}: {
  title: string;
  description: DisplayCopy;
  action?: ReactNode;
  role: "alert" | "status";
  tone: "neutral" | "danger";
}): ReactElement {
  return (
    <section
      aria-live={role === "alert" ? "assertive" : "polite"}
      className={`rounded-xl border p-5 ${
        tone === "danger"
          ? "border-red-200 bg-red-50 text-red-950"
          : "border-[var(--border)] bg-[var(--surface)] text-[var(--text-primary)]"
      }`}
      role={role}
    >
      <h2 className="text-base font-semibold">{title}</h2>
      <p className="mt-1 text-sm leading-6"><DisplayText copy={description} /></p>
      {action ? <div className="mt-4">{action}</div> : null}
    </section>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: DisplayCopy;
  action?: ReactNode;
}): ReactElement {
  return (
    <StateMessage
      action={action}
      description={description}
      role="status"
      title={title}
      tone="neutral"
    />
  );
}

export function ErrorState({
  title,
  description,
  retryAction,
}: {
  title: string;
  description: DisplayCopy;
  retryAction?: ReactNode;
}): ReactElement {
  return (
    <StateMessage
      action={retryAction}
      description={description}
      role="alert"
      title={title}
      tone="danger"
    />
  );
}

export function PermissionNotice({
  currentRole,
  requiredRole,
  description,
}: {
  currentRole: string;
  requiredRole: string;
  description?: DisplayCopy;
}): ReactElement {
  return (
    <aside
      className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950"
      role="note"
    >
      <p className="font-semibold">当前操作不可用</p>
      <p className="mt-1">
        {description ? (
          <DisplayText copy={description} />
        ) : (
          <>当前角色：{currentRole}；需要角色：{requiredRole}</>
        )}
      </p>
    </aside>
  );
}

export function DesktopOnlyNotice({
  action,
  description,
}: {
  action: string;
  description?: DisplayCopy;
}): ReactElement {
  return (
    <aside
      className="rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-950"
      role="note"
    >
      <p className="font-semibold">此操作需要电脑端</p>
      <p className="mt-1">
        {description ? <DisplayText copy={description} /> : <>请在电脑端继续{action}。</>}
      </p>
    </aside>
  );
}

export function Skeleton({
  label = "正在加载",
}: {
  label?: string;
}): ReactElement {
  return (
    <div aria-busy="true" aria-label={label} className="space-y-3" role="status">
      <span className="sr-only">{label}</span>
      <div
        aria-hidden="true"
        className="h-4 w-2/5 animate-pulse rounded bg-slate-200"
      />
      <div
        aria-hidden="true"
        className="h-20 animate-pulse rounded-lg bg-slate-100"
      />
    </div>
  );
}

export type DetailTab = {
  id: string;
  label: string;
  panel: ReactNode;
};

export function DetailTabs({
  tabs,
  activeTab,
  onTabChange,
  ariaLabel,
}: {
  tabs: DetailTab[];
  activeTab: string;
  onTabChange: (tabId: string) => void;
  ariaLabel: string;
}): ReactElement {
  const baseId = useId();
  const activeIndex = Math.max(
    0,
    tabs.findIndex((tab) => tab.id === activeTab),
  );
  const selectedTab = tabs[activeIndex];

  function handleKeyDown(
    event: KeyboardEvent<HTMLButtonElement>,
    index: number,
  ) {
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight") nextIndex = (index + 1) % tabs.length;
    if (event.key === "ArrowLeft") nextIndex = (index - 1 + tabs.length) % tabs.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = tabs.length - 1;
    if (nextIndex === null) return;

    event.preventDefault();
    const nextButton = event.currentTarget.parentElement?.querySelectorAll("button")[
      nextIndex
    ];
    nextButton?.focus();
    onTabChange(tabs[nextIndex].id);
  }

  if (!selectedTab) {
    return (
      <EmptyState
        description="当前没有可显示的详情标签"
        title="暂无详情"
      />
    );
  }

  return (
    <div>
      <div
        aria-label={ariaLabel}
        className="flex gap-1 overflow-x-auto border-b border-[var(--border)]"
        role="tablist"
      >
        {tabs.map((tab, index) => {
          const selected = index === activeIndex;
          const tabId = `${baseId}-tab-${tab.id}`;
          const panelId = `${baseId}-panel-${tab.id}`;
          return (
            <button
              aria-controls={panelId}
              aria-selected={selected}
              className={`min-h-10 whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium ${
                selected
                  ? "border-[var(--brand)] text-[var(--brand)]"
                  : "border-transparent text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
              }`}
              id={tabId}
              key={tab.id}
              onClick={() => onTabChange(tab.id)}
              onKeyDown={(event) => handleKeyDown(event, index)}
              role="tab"
              tabIndex={selected ? 0 : -1}
              type="button"
            >
              {tab.label}
            </button>
          );
        })}
      </div>
      <section
        aria-labelledby={`${baseId}-tab-${selectedTab.id}`}
        className="pt-5"
        id={`${baseId}-panel-${selectedTab.id}`}
        role="tabpanel"
      >
        {selectedTab.panel}
      </section>
    </div>
  );
}

export function DataTableFrame({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}): ReactElement {
  return (
    <div
      aria-label={label}
      className="overflow-x-auto rounded-xl border border-[var(--border)] bg-[var(--surface)]"
      role="region"
      tabIndex={0}
    >
      {children}
    </div>
  );
}
