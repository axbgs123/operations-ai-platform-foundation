"use client";

import { useExperiencePreferences } from "./experience-preferences-context";

function ControlFields() {
  const {
    copyMode,
    pageGuidance,
    setCopyMode,
    setPageGuidance,
  } = useExperiencePreferences();
  return (
    <div className="flex flex-wrap items-center gap-2" aria-label="界面说明设置">
      <div
        aria-label="文案模式"
        className="inline-flex rounded-lg border bg-white p-1"
        role="radiogroup"
      >
        {([
          ["simple", "易懂"],
          ["professional", "专业"],
        ] as const).map(([value, label]) => (
          <label
            className={`relative cursor-pointer rounded-md px-2.5 py-1.5 text-sm focus-within:ring-2 focus-within:ring-[var(--brand)] focus-within:ring-offset-2 ${
              copyMode === value
                ? "bg-[var(--brand)] font-semibold text-white"
                : "text-[var(--text-secondary)]"
            }`}
            key={value}
          >
            <input
              checked={copyMode === value}
              className="absolute inset-0 cursor-pointer opacity-0"
              name="copy-mode"
              onChange={() => setCopyMode(value)}
              type="radio"
              value={value}
            />
            {label}
          </label>
        ))}
      </div>
      <button
        aria-checked={pageGuidance === "on"}
        aria-label="页面引导"
        className="rounded-lg border bg-white px-3 py-2 text-sm"
        onClick={() => setPageGuidance(pageGuidance === "on" ? "off" : "on")}
        role="switch"
        type="button"
      >
        引导：{pageGuidance === "on" ? "开" : "关"}
      </button>
    </div>
  );
}

export function ExperienceControls({ compact = false }: { compact?: boolean }) {
  if (!compact) return <ControlFields />;
  return (
    <details className="relative">
      <summary className="cursor-pointer rounded-lg border bg-white px-3 py-2 text-sm">
        界面说明
      </summary>
      <div className="absolute right-0 z-50 mt-2 w-64 rounded-xl border bg-white p-3 shadow-lg max-md:static max-md:w-[calc(100vw-2rem)]">
        <ControlFields />
      </div>
    </details>
  );
}
