"use client";

import { useEffect, useState } from "react";

import { useWorkbenchShellContext } from "@/components/workbench/workspace-shell";
import {
  EmptyState,
  ErrorState,
  PageHeader,
  Panel,
  StatusBadge,
} from "@/components/workbench/ui";
import {
  listTrash,
  readRetentionPolicy,
  restoreTrashContent,
  type RetentionPolicy,
  type TrashItem,
} from "@/lib/export-api";

type Role = "admin" | "editor" | "viewer";
type TrashViewItem = Pick<
  TrashItem,
  | "id"
  | "resource_id"
  | "resource_type"
  | "deleted_by"
  | "deleted_at"
  | "scheduled_purge_at"
  | "deletion_reason"
  | "status"
  | "restored_at"
> & {
  title?: string;
  platform?: "douyin" | "xiaohongshu";
  account_name?: string;
  evidence_hold_reason?: string | null;
};

export type TrashFixture = {
  policy: Pick<
    RetentionPolicy,
    "strategy" | "version" | "retention_seconds" | "effective_at"
  >;
  items: TrashViewItem[];
};

const statusLabels: Record<string, string> = {
  recoverable: "可恢复",
  purging: "清理中",
  purged: "已清理",
  restored: "已恢复",
};

export function TrashCenter({
  workspaceId,
  role: suppliedRole,
  fixture,
  evaluatedAt,
}: {
  workspaceId: string;
  role?: Role;
  fixture?: TrashFixture;
  evaluatedAt?: string;
}) {
  const context = useWorkbenchShellContext();
  const role = suppliedRole ?? context?.role ?? "viewer";
  const [items, setItems] = useState<TrashViewItem[]>(fixture?.items ?? []);
  const [policy, setPolicy] = useState<TrashFixture["policy"] | null>(
    fixture?.policy ?? null,
  );
  const [loading, setLoading] = useState(!fixture);
  const [error, setError] = useState("");
  const now = evaluatedAt ? Date.parse(evaluatedAt) : 0;
  const canRestore = role === "admin" || role === "editor";

  useEffect(() => {
    if (fixture) return;
    let active = true;
    Promise.all([listTrash(workspaceId), readRetentionPolicy(workspaceId)])
      .then(([nextItems, nextPolicy]) => {
        if (!active) return;
        setItems(nextItems);
        setPolicy(nextPolicy);
      })
      .catch((caught: unknown) => {
        if (active) {
          setError(caught instanceof Error ? caught.message : "回收站加载失败");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [fixture, workspaceId]);

  async function restore(item: TrashViewItem) {
    setError("");
    try {
      await restoreTrashContent(
        workspaceId,
        item.resource_id,
        sessionStorage.getItem("workspace_csrf") ?? "",
      );
      setItems((current) =>
        current.map((candidate) =>
          candidate.id === item.id
            ? { ...candidate, status: "restored", restored_at: new Date().toISOString() }
            : candidate,
        ),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "恢复失败");
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        description="这里只展示支持软删除的内容资源。工作区删除位于设置的危险操作，并使用独立的二次确认。"
        title="内容回收站"
      />
      <Panel title="保留策略">
        <dl className="grid gap-3 text-sm sm:grid-cols-3">
          <div><dt>策略</dt><dd>{policy?.strategy ?? "当前记录未提供"}</dd></div>
          <div><dt>版本</dt><dd>{policy?.version ?? "当前记录未提供"}</dd></div>
          <div><dt>保留秒数</dt><dd>{policy?.retention_seconds ?? "Evidence 决定"}</dd></div>
        </dl>
        <p className="mt-3 text-sm text-[var(--text-secondary)]">
          Evidence 保留会阻止普通清理；状态和清理时间完全以服务端为准。
        </p>
      </Panel>
      {error ? <ErrorState description={error} title="回收站请求失败" /> : null}
      <Panel title="已删除内容">
        {loading ? <p role="status">正在加载回收站…</p> : null}
        {!loading && items.length === 0 ? (
          <EmptyState description="软删除的内容会在保留期内显示在这里。" title="回收站为空" />
        ) : null}
        <div className="space-y-3">
          {items.map((item) => {
            const expired =
              now > 0 && Date.parse(item.scheduled_purge_at) <= now;
            return (
              <article className="rounded-lg border p-4" key={item.id}>
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <strong>{item.title ?? `${item.resource_type} · ${item.resource_id}`}</strong>
                    <p className="mt-1 text-sm text-[var(--text-secondary)]">
                      {item.platform ? (item.platform === "douyin" ? "抖音" : "小红书") : "平台当前记录未提供"}
                      {" · "}
                      {item.account_name ?? "账号当前记录未提供"}
                    </p>
                  </div>
                  <StatusBadge tone={item.status === "recoverable" ? "warning" : "neutral"}>
                    {statusLabels[item.status] ?? item.status}
                  </StatusBadge>
                </div>
                <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-3">
                  <div><dt>删除人</dt><dd>{item.deleted_by ?? "系统"}</dd></div>
                  <div><dt>删除时间</dt><dd>{item.deleted_at}</dd></div>
                  <div><dt>可恢复截止时间</dt><dd>{item.scheduled_purge_at}</dd></div>
                </dl>
                {item.evidence_hold_reason ? (
                  <p className="mt-3 text-sm text-amber-800">
                    Evidence 保留：{item.evidence_hold_reason}
                  </p>
                ) : null}
                {canRestore && item.status === "recoverable" && !expired ? (
                  <button
                    className="mt-4 rounded-lg border px-4 py-2"
                    onClick={() => void restore(item)}
                    type="button"
                  >
                    恢复内容
                  </button>
                ) : null}
                {expired && item.status === "recoverable" ? (
                  <p className="mt-3 text-sm text-amber-800">
                    已超过恢复截止时间，不再提供恢复操作。
                  </p>
                ) : null}
              </article>
            );
          })}
        </div>
      </Panel>
    </div>
  );
}
