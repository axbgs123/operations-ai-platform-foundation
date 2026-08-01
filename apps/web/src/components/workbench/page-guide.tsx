"use client";

import { useState } from "react";

import { useExperiencePreferences } from "./experience-preferences-context";
import {
  copyForMode,
  OPERATOR_COPY_CATALOG,
  type ModeAwareCopy,
  type OperatorPageId,
} from "./operator-copy-catalog";
import { PAGE_GUIDANCE_CATALOG, nextActionForRole } from "./page-guidance-catalog";
import { useWorkbenchShellContext } from "./workspace-shell";

const viewerSteps: readonly ModeAwareCopy[] = [
  {
    simple: "查看页面中已有的数据、状态和说明。",
    professional: "只读查看当前工作区已有记录和安全状态。",
  },
  {
    simple: "需要新增、修改或确认时，请联系管理员或编辑者。",
    professional: "写操作仍由服务端权限控制，请联系 Admin 或 Editor。",
  },
];

function GuideList({ title, items }: { title: string; items: readonly string[] }) {
  return (
    <div>
      <h2 className="text-sm font-semibold">{title}</h2>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm leading-6">
        {items.map((item) => <li key={item}>{item}</li>)}
      </ul>
    </div>
  );
}

export function PageGuide({ pageId }: { pageId: OperatorPageId }) {
  const [expanded, setExpanded] = useState(false);
  const context = useWorkbenchShellContext();
  const { copyMode, pageGuidance } = useExperiencePreferences();
  if (!context) throw new Error("PageGuide requires WorkspaceShell context");
  const page = OPERATOR_COPY_CATALOG[pageId];
  const guide = PAGE_GUIDANCE_CATALOG[pageId];
  const next = nextActionForRole(guide, context.role);
  const text = (value: ModeAwareCopy) => copyForMode(value, copyMode);
  const steps = context.role === "viewer"
    ? [next.label, ...viewerSteps].map(text)
    : guide.steps.map(text);

  return (
    <section aria-label={`${page.title}页面说明`} className="mt-2 max-w-4xl">
      <p className="text-sm leading-6 text-[var(--text-secondary)]">
        {text(page.purpose)}
      </p>
      {page.safety ? (
        <p className="mt-2 text-sm font-medium text-amber-900" role="note">
          {text(page.safety)}
        </p>
      ) : null}
      {pageGuidance === "on" ? (
        <div className="mt-3 rounded-xl border border-blue-200 bg-blue-50 p-4 text-blue-950">
          <p className="text-sm">
            <strong>建议先做</strong>：<span>{text(next.label)}</span>
          </p>
          <button
            aria-expanded={expanded}
            className="mt-3 rounded-lg border border-blue-300 bg-white px-3 py-2 text-sm font-semibold"
            onClick={() => setExpanded((value) => !value)}
            type="button"
          >
            {expanded ? "收起操作说明" : "查看操作说明"}
          </button>
          {expanded ? (
            <div
              aria-label={`${page.title}操作说明`}
              className="mt-4 grid gap-4 lg:grid-cols-3"
              role="region"
            >
              <GuideList title="怎么使用" items={steps} />
              <GuideList title="你会看到什么" items={guide.concepts.map(text)} />
              <GuideList title="常见情况" items={guide.blockers.map(text)} />
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
