"use client";

import { useEffect, useState, type ReactElement } from "react";

import type { AgentConfirmationData } from "@/lib/agent-api";

import { agentToolLabel } from "./run-timeline";
import {
  DesktopOnlyNotice,
  EmptyState,
  StatusBadge,
} from "@/components/workbench/ui";


export function ConfirmationInbox({
  confirmations,
  role,
  onDecision,
}: {
  confirmations: AgentConfirmationData[];
  role: "admin" | "editor" | "viewer";
  onDecision?: (
    confirmation: AgentConfirmationData,
    decision: "approve" | "reject",
  ) => void;
}): ReactElement {
  const [mobile, setMobile] = useState(false);
  useEffect(() => {
    const query = window.matchMedia("(max-width: 639px)");
    const update = () => setMobile(query.matches);
    update();
    query.addEventListener?.("change", update);
    return () => query.removeEventListener?.("change", update);
  }, []);
  const pending = confirmations.filter((item) => item.status === "pending");
  if (!pending.length) {
    return (
      <EmptyState
        description="智能体遇到会写入正式记录的操作时，会在这里停下来等你决定。"
        title="当前没有待确认操作"
      />
    );
  }
  return (
    <ul className="space-y-3">
      {pending.map((confirmation) => (
        <li className="rounded-lg border border-amber-200 bg-amber-50 p-4" key={confirmation.id}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <strong>{agentToolLabel(confirmation.tool_name)}</strong>
            <StatusBadge tone="warning">等待确认</StatusBadge>
          </div>
          <p className="mt-2 text-sm">这一步需要你确认后才会继续。</p>
          <p className="mt-1 text-xs text-amber-900">
            只展示字段名称，不展示可能含有敏感内容的参数值。
          </p>
          {mobile ? (
            <div className="mt-3">
              <DesktopOnlyNotice action="确认受保护操作" />
            </div>
          ) : role !== "viewer" ? (
            <div className="mt-3 flex gap-2">
              <button
                className="rounded-lg bg-[var(--brand)] px-4 py-2 text-sm font-semibold text-white"
                onClick={() => onDecision?.(confirmation, "approve")}
                type="button"
              >
                确认继续
              </button>
              <button
                className="rounded-lg border px-4 py-2 text-sm font-semibold"
                onClick={() => onDecision?.(confirmation, "reject")}
                type="button"
              >
                拒绝此操作
              </button>
            </div>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
