"use client";

import { useEffect, useState } from "react";

import { GuidedPageHeader } from "@/components/workbench/guided-page-header";
import { useExperiencePreferences } from "@/components/workbench/experience-preferences-context";
import { copyForMode, type ModeAwareCopy } from "@/components/workbench/operator-copy-catalog";
import { useWorkbenchShellContext } from "@/components/workbench/workspace-shell";
import {
  DesktopOnlyNotice,
  EmptyState,
  ErrorState,
  Panel,
  StatusBadge,
} from "@/components/workbench/ui";
import {
  confirmZipRestore,
  createExportTask,
  listExportTasks,
  previewJsonRestore,
  previewZipRestore,
  readExportTask,
  type ExportTask,
  type FullRestore,
  type RestorePreview,
} from "@/lib/export-api";

type Role = "admin" | "editor" | "viewer";

export type ExportBackupFixture = {
  tasks: Array<
    Pick<
      ExportTask,
      | "id"
      | "kind"
      | "status"
      | "created_at"
      | "completed_at"
      | "download_expires_at"
      | "error_code"
      | "requested_by"
      | "file_name"
    >
  >;
  restorePreview: Array<{
    action: "create" | "overwrite" | "skip" | "conflict";
    record_type: string;
    reason: string;
  }>;
};

const TYPES = [
  {
    kind: "csv",
    title: "CSV 内容与运营数据",
    includes: "内容字段、平台字段、运营指标、原始时区和空值",
    excludes: "媒体正文、模型配置和知识文档正文",
  },
  {
    kind: "markdown",
    title: "Markdown 单条分析报告",
    includes: "内容信息、分析版本、运营证据、有效引用和免责声明",
    excludes: "完整 Prompt、供应商错误正文和秘密",
  },
  {
    kind: "json",
    title: "JSON 轻量备份",
    includes: "可迁移结构化记录、稳定标识和安全资产元数据",
    excludes: "媒体正文、Embedding、向量和临时任务租约",
  },
  {
    kind: "zip",
    title: "ZIP 完整备份",
    includes: "校验和清单、授权媒体、知识原件和结构化记录",
    excludes: "秘密、临时签名地址、Worker claim、lease和heartbeat",
  },
] as const;

const SECRET_EXCLUSIONS =
  "始终排除：邀请码、会话、Token及哈希、API Key及密文、Provider Workspace ID、Cookie、临时签名URL、Prompt、Embedding和向量、未授权知识正文、Worker claim、lease和heartbeat。";

const actionLabels = {
  create: "新增",
  overwrite: "覆盖",
  skip: "跳过",
  conflict: "冲突",
} as const;

const restoreCopy: ModeAwareCopy = {
  simple: "完整备份恢复前检查",
  professional: "ZIP 完整恢复",
};

const exportSafetyCopy: ModeAwareCopy = {
  simple: "系统会先检查版本、文件和冲突；确认恢复前不会改动正式数据。",
  professional: "所有文件通过异步任务生成；短期下载地址不写入浏览器存储，恢复必须先预览再确认。",
};

const exportHistoryEmptyCopy: ModeAwareCopy = {
  simple: "创建导出后会在这里显示状态、完成时间和失败原因编号。",
  professional: "创建导出后会在这里显示状态、完成时间和安全错误码。",
};

const internalStateCopy: Record<string, ModeAwareCopy> = {
  configuration_required: {
    simple: "还没有完成所需配置",
    professional: "configuration_required",
  },
  compensation_required: {
    simple: "自动清理没有完成，需要管理员处理",
    professional: "compensation_required",
  },
  provider_outcome_unknown: {
    simple: "模型服务是否已经计费暂时无法确认，请勿直接重复提交",
    professional: "provider_outcome_unknown",
  },
};

export function ExportBackupCenter({
  workspaceId,
  role: suppliedRole,
  fixture,
  evaluatedAt,
}: {
  workspaceId: string;
  role?: Role;
  fixture?: ExportBackupFixture;
  evaluatedAt?: string;
}) {
  const context = useWorkbenchShellContext();
  const { copyMode } = useExperiencePreferences();
  const role = suppliedRole ?? context?.role ?? "viewer";
  const [tasks, setTasks] = useState<ExportBackupFixture["tasks"]>(
    fixture?.tasks ?? [],
  );
  const [loading, setLoading] = useState(!fixture);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");
  const [contentId, setContentId] = useState("");
  const [jsonPreview, setJsonPreview] = useState<RestorePreview | null>(null);
  const [zipRestore, setZipRestore] = useState<FullRestore | null>(null);
  const now = evaluatedAt ? Date.parse(evaluatedAt) : 0;
  const canExport = role === "admin" || role === "editor";
  const canRestore = role === "admin";
  const displayState = (value: string) => (
    internalStateCopy[value]
      ? copyForMode(internalStateCopy[value], copyMode)
      : value
  );

  useEffect(() => {
    if (fixture) return;
    let active = true;
    listExportTasks(workspaceId)
      .then((page) => {
        if (active) setTasks(page.items);
      })
      .catch((caught: unknown) => {
        if (active) {
          setError(caught instanceof Error ? caught.message : "导出任务加载失败");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [fixture, workspaceId]);

  async function create(kind: "csv" | "markdown" | "json" | "zip") {
    setBusy(kind);
    setError("");
    try {
      const task = await createExportTask(
        workspaceId,
        kind,
        sessionStorage.getItem("workspace_csrf") ?? "",
        kind === "markdown" ? contentId.trim() : undefined,
      );
      setTasks((current) => [task, ...current.filter((item) => item.id !== task.id)]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "创建导出失败");
    } finally {
      setBusy("");
    }
  }

  async function loadDownload(taskId: string) {
    setBusy(taskId);
    setNotice("");
    setError("");
    try {
      const task = await readExportTask(workspaceId, taskId);
      if (!task.download_url) {
        setNotice("文件尚未生成可用的短期下载地址。");
        return;
      }
      window.location.assign(task.download_url);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "下载地址生成失败");
    } finally {
      setBusy("");
    }
  }

  async function previewJson(file: File) {
    setBusy("json-restore");
    setError("");
    try {
      setJsonPreview(
        await previewJsonRestore(
          workspaceId,
          file,
          sessionStorage.getItem("workspace_csrf") ?? "",
        ),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "JSON 恢复预览失败");
    } finally {
      setBusy("");
    }
  }

  async function previewZip(file: File) {
    setBusy("zip-restore");
    setError("");
    try {
      setZipRestore(
        await previewZipRestore(
          workspaceId,
          file,
          sessionStorage.getItem("workspace_csrf") ?? "",
        ),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "ZIP 恢复预览失败");
    } finally {
      setBusy("");
    }
  }

  async function confirmZip() {
    if (!zipRestore) return;
    setBusy("zip-confirm");
    setError("");
    try {
      const restored = await confirmZipRestore(
        workspaceId,
        zipRestore,
        sessionStorage.getItem("workspace_csrf") ?? "",
      );
      setZipRestore(restored);
      setNotice("完整恢复已进入受控异步任务；完成前不会显示为成功。");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "ZIP 恢复确认失败");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="space-y-6">
      <GuidedPageHeader context={exportSafetyCopy} pageId="exports" />
      <Panel title="数据边界">
        <p className="text-sm leading-6 text-[var(--text-secondary)]">
          {SECRET_EXCLUSIONS}
        </p>
      </Panel>
      <section className="grid gap-4 lg:grid-cols-2" aria-label="导出和备份类型">
        {TYPES.map((type) => (
          <Panel description={`包含：${type.includes}`} key={type.kind} title={type.title}>
            <p className="text-sm text-[var(--text-secondary)]">
              排除：{type.excludes}
            </p>
            <p className="mt-2 text-sm">范围：当前工作区；平台/账号保持各自归属</p>
            {type.kind === "markdown" && canExport ? (
              <label className="mt-3 block text-sm">
                内容 ID
                <input
                  className="mt-1 w-full rounded-lg border px-3 py-2"
                  onChange={(event) => setContentId(event.target.value)}
                  placeholder="仅导出该内容的单条报告"
                  value={contentId}
                />
              </label>
            ) : null}
            {canExport ? (
              <button
                className="mt-4 rounded-lg bg-[var(--brand)] px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
                disabled={
                  busy === type.kind
                  || (type.kind === "markdown" && contentId.trim() === "")
                }
                onClick={() => void create(type.kind)}
                type="button"
              >
                创建{type.title}
              </button>
            ) : null}
          </Panel>
        ))}
      </section>
      <section className="grid gap-4 lg:grid-cols-2">
        <Panel
          description="JSON 只恢复允许的结构化数据；未知版本和损坏引用会阻断。"
          title="JSON 恢复预览"
        >
          <RestoreActions
            items={
              jsonPreview?.items.map((item) => ({
                action: item.action,
                record_type: item.record_type,
                reason: item.reason,
              })) ?? fixture?.restorePreview ?? []
            }
          />
          {jsonPreview ? (
            <p className="mt-3 text-sm" role="status">
              预览 {jsonPreview.blocked ? "被冲突阻断" : "验证通过"}；
              JSON 预览不会修改正式数据。
            </p>
          ) : null}
          {canRestore ? (
            <label className="mt-4 inline-block cursor-pointer rounded-lg border px-4 py-2">
              选择 JSON 并生成预览
              <input
                accept="application/json,.json"
                className="sr-only"
                disabled={busy === "json-restore"}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void previewJson(file);
                  event.target.value = "";
                }}
                type="file"
              />
            </label>
          ) : null}
        </Panel>
        <Panel
          description="显示校验和、媒体、知识原件与向量重建状态；失败不会显示为部分成功。"
          title={copyForMode(restoreCopy, copyMode)}
        >
          <DesktopOnlyNotice action={copyForMode(restoreCopy, copyMode)} />
          {zipRestore ? (
            <div className="mt-3 space-y-2 text-sm" role="status">
              <p>
                阶段：{displayState(zipRestore.phase)}；状态：
                {displayState(zipRestore.status)}
              </p>
              <p>预览 ID：{zipRestore.preview_id}</p>
              {canRestore && zipRestore.phase === "preview_ready" ? (
                <button
                  className="rounded-lg bg-red-700 px-4 py-2 font-semibold text-white"
                  disabled={busy === "zip-confirm"}
                  onClick={() => void confirmZip()}
                  type="button"
                >
                  再次确认并开始完整恢复
                </button>
              ) : null}
            </div>
          ) : null}
          {canRestore ? (
            <label className="mt-4 hidden cursor-pointer rounded-lg border px-4 py-2 md:inline-block">
              选择 ZIP 并生成预览
              <input
                accept="application/zip,.zip"
                className="sr-only"
                disabled={busy === "zip-restore"}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void previewZip(file);
                  event.target.value = "";
                }}
                type="file"
              />
            </label>
          ) : null}
        </Panel>
      </section>
      {error ? <ErrorState description={error} title="数据管理加载失败" /> : null}
      {notice ? <p className="text-sm text-blue-800" role="status">{notice}</p> : null}
      <Panel title="任务历史">
        {loading ? <p role="status">正在加载导出任务…</p> : null}
        {!loading && tasks.length === 0 ? (
          <EmptyState
            description={exportHistoryEmptyCopy}
            title="暂无导出任务"
          />
        ) : null}
        <div className="space-y-3">
          {tasks.map((task) => {
            const expired =
              now > 0
              &&
              task.download_expires_at !== null
              && Date.parse(task.download_expires_at) <= now;
            return (
              <article className="rounded-lg border p-4" key={task.id}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <strong>{TYPES.find((item) => item.kind === task.kind)?.title}</strong>
                  <StatusBadge
                    tone={task.status === "failed" ? "danger" : task.status === "succeeded" ? "success" : "info"}
                  >
                    {displayState(task.status)}
                  </StatusBadge>
                </div>
                <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-3">
                  <div><dt>创建人</dt><dd>{task.requested_by}</dd></div>
                  <div><dt>创建时间</dt><dd>{task.created_at}</dd></div>
                  <div><dt>完成时间</dt><dd>{task.completed_at ?? "未完成"}</dd></div>
                  <div><dt>下载过期时间</dt><dd>{task.download_expires_at ?? "尚未生成"}</dd></div>
                  <div>
                    <dt>
                      {copyMode === "simple" ? "失败原因编号" : "安全错误码"}
                    </dt>
                    <dd>{task.error_code ?? "无"}</dd>
                  </div>
                </dl>
                {expired ? (
                  <p className="mt-3 text-sm text-amber-800">
                    下载地址已过期；请重新生成，不继续使用旧地址。
                  </p>
                ) : null}
                {canExport && task.status === "succeeded" && !expired ? (
                  <button
                    className="mt-3 rounded-lg border px-3 py-2 text-sm font-semibold"
                    disabled={busy === task.id}
                    onClick={() => void loadDownload(task.id)}
                    type="button"
                  >
                    生成短期下载地址
                  </button>
                ) : null}
              </article>
            );
          })}
        </div>
      </Panel>
    </div>
  );
}

function RestoreActions({
  items,
}: {
  items: ExportBackupFixture["restorePreview"];
}) {
  return (
    <div className="grid grid-cols-2 gap-2">
      {(items.length > 0
        ? items
        : (Object.keys(actionLabels) as Array<keyof typeof actionLabels>).map(
            (action) => ({ action, record_type: "预览后显示", reason: "尚未上传" }),
          )
      ).map((item) => (
        <article className="rounded-lg bg-slate-50 p-3 text-sm" key={`${item.action}:${item.record_type}`}>
          <StatusBadge tone={item.action === "conflict" ? "danger" : item.action === "overwrite" ? "warning" : "neutral"}>
            {actionLabels[item.action]}
          </StatusBadge>
          <p className="mt-2">{item.record_type} · {item.reason}</p>
        </article>
      ))}
    </div>
  );
}
