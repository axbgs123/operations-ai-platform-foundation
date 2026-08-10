"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  useEffect,
  useMemo,
  useState,
  type ReactElement,
} from "react";

import type { WorkbenchAccount } from "@/components/workbench/scope-query";
import { useWorkbenchShellContext } from "@/components/workbench/workspace-shell";
import {
  DataTableFrame,
  DesktopOnlyNotice,
  EmptyState,
  ErrorState,
  PermissionNotice,
  Skeleton,
  StatusBadge,
} from "@/components/workbench/ui";
import { GuidedPageHeader, GuidedPageShell } from "@/components/workbench/guided-page-header";
import { useExperiencePreferences } from "@/components/workbench/experience-preferences-context";
import {
  displayText,
  importHistoryActionCopy,
  importMethodDescriptionCopy,
} from "@/components/workbench/operator-display-copy";
import {
  loadImportHistory,
  type ImportHistoryData,
} from "@/lib/import-api";

import { ExtensionCaptureReview } from "./extension-capture-review";
import { ExtensionPairingPanel } from "@/components/extension/extension-pairing-panel";
import { ImportReview } from "./import-review";
import { ScreenshotReview } from "./screenshot-review";


export type ImportMethod =
  | "manual"
  | "tabular"
  | "screenshot"
  | "extension";

const importMethods: {
  id: ImportMethod;
  label: string;
  description: string;
}[] = [
  {
    id: "manual",
    label: "手动录入",
    description: "逐条录入内容和可用的初始指标，先预览再确认。",
  },
  {
    id: "tabular",
    label: "Excel / CSV",
    description: "字段映射、逐行错误、重复判断和批量确认。",
  },
  {
    id: "screenshot",
    label: "截图识别",
    description: "Mock 或受控视觉识别，低置信度必须人工修正。",
  },
  {
    id: "extension",
    label: "Capture Extension",
    description: "读取扩展暂存任务，正式写入只能在 Web 中确认。",
  },
];

const platformLabel = {
  douyin: "抖音",
  xiaohongshu: "小红书",
} as const;

const methodLabel = {
  manual: "手动录入",
  tabular: "Excel / CSV",
  screenshot: "截图识别",
  extension: "Capture Extension",
} as const;

const historyStatusLabel = {
  waiting_confirmation: "等待人工确认",
  processing: "处理中",
  confirmed: "已确认入库",
  failed: "失败",
  cancelled: "已取消",
} as const;

function historyTone(
  status: keyof typeof historyStatusLabel,
): "neutral" | "info" | "success" | "warning" | "danger" {
  if (status === "failed") return "danger";
  if (status === "confirmed") return "success";
  if (status === "processing") return "info";
  if (status === "waiting_confirmation") return "warning";
  return "neutral";
}

function historyHref(
  workspaceId: string,
  item: ImportHistoryData["items"][number],
): string {
  const query = new URLSearchParams({
    platform: item.platform,
    method: item.method,
  });
  if (item.account_id) query.set("account", item.account_id);
  if (item.method === "extension") {
    query.set("capture_task_id", item.id);
  } else {
    query.set("batch_id", item.id);
  }
  return `/workspaces/${workspaceId}/imports?${query}`;
}

function ImportHistory({
  data,
  onPageChange,
  role,
  workspaceId,
}: {
  data: ImportHistoryData;
  onPageChange: (page: number) => void;
  role: "admin" | "editor" | "viewer";
  workspaceId: string;
}): ReactElement {
  const { copyMode } = useExperiencePreferences();
  return (
    <section className="space-y-4" aria-labelledby="import-history-heading">
      <div>
        <h2 className="text-lg font-semibold" id="import-history-heading">
          导入历史
        </h2>
        <p className="mt-1 text-sm text-[var(--text-secondary)]">
          {copyMode === "simple"
            ? "仅展示安全状态、统计和下一步，不返回文件、截图识别正文或令牌。"
            : "仅展示安全状态、统计和下一步，不返回文件、截图、OCR正文或令牌。"}
        </p>
      </div>
      {!data.items.length ? (
        <EmptyState
          description="完成一次暂存预览后，任务会显示在这里。"
          title="暂无导入历史"
        />
      ) : (
        <>
          <DataTableFrame label="导入历史桌面列表">
            <table
              aria-label="导入历史桌面列表"
              className="hidden min-w-[960px] w-full text-left text-sm md:table"
            >
              <thead className="bg-slate-50 text-[var(--text-secondary)]">
                <tr>
                  {[
                    "方式",
                    "范围",
                    "状态",
                    "新增/更新/重复/失败",
                    "创建/确认",
                    "操作者",
                    "安全错误码",
                    "下一步",
                  ].map((label) => (
                    <th className="px-3 py-3" key={label}>{label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr className="border-t" key={`${item.method}:${item.id}`}>
                    <td className="px-3 py-3">{methodLabel[item.method]}</td>
                    <td className="px-3 py-3">
                      {platformLabel[item.platform]} ·{" "}
                      {item.account_name ?? "任务尚未绑定账号"}
                    </td>
                    <td className="px-3 py-3">
                      <StatusBadge tone={historyTone(item.status)}>
                        {historyStatusLabel[item.status]}
                      </StatusBadge>
                    </td>
                    <td className="px-3 py-3">
                      {item.counts.new}/{item.counts.update}/
                      {item.counts.suspected_duplicate}/{item.counts.failed}
                    </td>
                    <td className="px-3 py-3">
                      <p>{new Date(item.created_at).toLocaleString("zh-CN")}</p>
                      <p>{item.confirmed_at
                        ? new Date(item.confirmed_at).toLocaleString("zh-CN")
                        : "尚未确认"}</p>
                    </td>
                    <td className="px-3 py-3">
                      {item.operator_name ?? "当前记录未提供"}
                    </td>
                    <td className="px-3 py-3">
                      {item.safe_error_code ?? "无"}
                    </td>
                    <td className="px-3 py-3">
                      {item.next_action === "none" ? "无可用操作" : (
                        <Link
                          className="font-semibold text-[var(--brand)]"
                          href={historyHref(workspaceId, item)}
                        >
                          {displayText(importHistoryActionCopy(item.next_action, role), copyMode)}
                        </Link>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </DataTableFrame>
          <ul
            aria-label="导入历史移动卡片"
            className="grid grid-cols-1 gap-3 md:hidden"
          >
            {data.items.map((item) => (
              <li className="rounded-xl border bg-white p-4" key={item.id}>
                <div className="flex items-start justify-between gap-3">
                  <p className="font-semibold">{methodLabel[item.method]}</p>
                  <StatusBadge tone={historyTone(item.status)}>
                    {historyStatusLabel[item.status]}
                  </StatusBadge>
                </div>
                <p className="mt-2 text-sm">
                  {platformLabel[item.platform]} ·{" "}
                  {item.account_name ?? "任务尚未绑定账号"}
                </p>
                <p className="mt-2 text-sm">
                  新增 {item.counts.new} · 更新 {item.counts.update} ·
                  重复 {item.counts.suspected_duplicate} · 失败 {item.counts.failed}
                </p>
                <p className="mt-2 text-sm">
                  安全错误码：{item.safe_error_code ?? "无"}
                </p>
                {item.next_action !== "none" ? (
                  <Link
                    className="mt-3 inline-flex font-semibold text-[var(--brand)]"
                    href={historyHref(workspaceId, item)}
                  >
                    {displayText(importHistoryActionCopy(item.next_action, role), copyMode)}
                  </Link>
                ) : null}
              </li>
            ))}
          </ul>
        </>
      )}
      {data.pages > 1 ? (
        <nav aria-label="导入历史分页" className="flex items-center justify-between">
          <button
            className="rounded-lg border bg-white px-3 py-2 disabled:opacity-50"
            disabled={data.page <= 1}
            onClick={() => onPageChange(data.page - 1)}
            type="button"
          >
            上一页
          </button>
          <span>第 {data.page} / {data.pages} 页，共 {data.total} 条</span>
          <button
            className="rounded-lg border bg-white px-3 py-2 disabled:opacity-50"
            disabled={data.page >= data.pages}
            onClick={() => onPageChange(data.page + 1)}
            type="button"
          >
            下一页
          </button>
        </nav>
      ) : null}
    </section>
  );
}

export function ImportCenter({
  workspaceId,
  accounts,
  platform,
  accountId,
  role,
  method,
  history,
  captureTaskId,
  batchId,
  onMethodChange,
  onScopeChange,
  onHistoryPageChange = () => undefined,
}: {
  workspaceId: string;
  accounts: WorkbenchAccount[];
  platform?: "douyin" | "xiaohongshu";
  accountId?: string;
  role: "admin" | "editor" | "viewer";
  method?: ImportMethod;
  history: ImportHistoryData;
  captureTaskId?: string;
  batchId?: string;
  onMethodChange: (method: ImportMethod) => void;
  onScopeChange: (scope: {
    platform?: "douyin" | "xiaohongshu";
    accountId?: string;
  }) => void;
  onHistoryPageChange?: (page: number) => void;
}): ReactElement {
  const { copyMode } = useExperiencePreferences();
  const writable = role !== "viewer";
  const visibleAccounts = accounts.filter(
    (account) => !platform || account.platform === platform,
  );
  const hasScope = Boolean(platform && accountId);
  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <GuidedPageHeader pageId="imports" />
      <ol
        aria-label="统一导入流程"
        className="grid grid-cols-2 gap-2 rounded-xl border bg-white p-4 text-center text-sm sm:grid-cols-5"
      >
        {["选择来源", "上传/采集", "暂存预览", "修正", "确认入库"].map(
          (step, index) => (
            <li className="rounded-lg bg-slate-50 px-3 py-2" key={step}>
              {index + 1}. {step}
            </li>
          ),
        )}
      </ol>
      <section
        aria-label="导入范围"
        className="grid gap-3 rounded-xl border bg-white p-4 sm:grid-cols-2"
      >
        <label className="text-sm font-medium">
          导入平台
          <select
            className="mt-1 min-h-10 w-full rounded-lg border bg-white px-3"
            disabled={!writable}
            onChange={(event) => {
              const nextPlatform = event.target.value
                ? event.target.value as "douyin" | "xiaohongshu"
                : undefined;
              onScopeChange({
                platform: nextPlatform,
                accountId: (
                  accounts.some(
                    (account) =>
                      account.account_id === accountId
                      && account.platform === nextPlatform,
                  )
                    ? accountId
                    : undefined
                ),
              });
            }}
            value={platform ?? ""}
          >
            <option value="">请选择平台</option>
            <option value="douyin">抖音</option>
            <option value="xiaohongshu">小红书</option>
          </select>
        </label>
        <label className="text-sm font-medium">
          导入账号
          <select
            className="mt-1 min-h-10 w-full rounded-lg border bg-white px-3"
            disabled={!writable || !platform}
            onChange={(event) => onScopeChange({
              platform,
              accountId: event.target.value || undefined,
            })}
            value={accountId ?? ""}
          >
            <option value="">请选择账号</option>
            {visibleAccounts.map((account) => (
              <option key={account.account_id} value={account.account_id}>
                {account.name}
              </option>
            ))}
          </select>
        </label>
      </section>

      {!writable ? (
        <PermissionNotice currentRole="查看者" requiredRole="编辑者或管理员" />
      ) : (
        <section aria-label="导入方式" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {importMethods.map((item) => (
            <button
              aria-label={item.label}
              aria-pressed={method === item.id}
              className={`rounded-xl border bg-white p-4 text-left ${
                method === item.id ? "border-[var(--brand)] ring-2 ring-violet-100" : ""
              }`}
              key={item.id}
              onClick={() => onMethodChange(item.id)}
              type="button"
            >
              <span className="font-semibold">{item.label}</span>
              <span className="mt-2 block text-sm text-[var(--text-secondary)]">
                {displayText(importMethodDescriptionCopy(item.id), copyMode)}
              </span>
            </button>
          ))}
        </section>
      )}

      {writable && method && !hasScope ? (
        <EmptyState
          description={{
            simple: "先选择抖音或小红书，再选择对应账号；两个平台的数据不会混在一起。",
            professional: "平台和账号共同决定指标、去重、栏目和正式写入范围。",
          }}
          title="请选择平台和账号"
        />
      ) : null}
      {writable && hasScope && method === "manual" ? (
        <ImportReview
          accountId={accountId!}
          initialBatchId={batchId}
          mode="manual"
          platform={platform!}
          workspaceId={workspaceId}
        />
      ) : null}
      {writable && hasScope && method === "tabular" ? (
        <div className="space-y-4">
          <div className="md:hidden">
            <DesktopOnlyNotice action="大型 Excel 字段映射和批量修正" />
          </div>
          <ImportReview
            accountId={accountId!}
            initialBatchId={batchId}
            mode="tabular"
            platform={platform!}
            workspaceId={workspaceId}
          />
        </div>
      ) : null}
      {writable && hasScope && method === "screenshot" ? (
        <ScreenshotReview
          accountId={accountId!}
          initialBatchId={batchId}
          platform={platform!}
          workspaceId={workspaceId}
        />
      ) : null}
      {hasScope && method === "extension" ? (
        writable && captureTaskId ? (
          <ExtensionCaptureReview
            accountId={accountId!}
            expectedPlatform={platform!}
            taskId={captureTaskId}
          />
        ) : (
          <section className="rounded-xl border bg-white p-5">
            <h2 className="font-semibold">连接 Capture Extension</h2>
            <div className="mt-3">
              <ExtensionPairingPanel
                role={role}
                triggerLabel="连接扩展"
                workspaceId={workspaceId}
              />
            </div>
            {writable ? (
              <p className="mt-4 text-sm text-[var(--text-secondary)]">
                页面版本、签名或敏感区域变化时扩展会安全停止。扩展令牌不能确认正式导入；成功识别后请通过任务链接回到 Web 人工确认。
              </p>
            ) : null}
          </section>
        )
      ) : null}
      <ImportHistory
        data={history}
        onPageChange={onHistoryPageChange}
        role={role}
        workspaceId={workspaceId}
      />
    </div>
  );
}

type ImportCenterState =
  | { status: "loading" }
  | { status: "ready"; history: ImportHistoryData; queryKey: string }
  | { status: "failed"; message: string; queryKey: string };

const METHOD_VALUES = new Set<ImportMethod>([
  "manual",
  "tabular",
  "screenshot",
  "extension",
]);

export function ImportCenterPage({
  workspaceId,
}: {
  workspaceId: string;
}): ReactElement {
  const context = useWorkbenchShellContext();
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const accounts = useMemo(() => context?.accounts ?? [], [context?.accounts]);
  const searchKey = searchParams.toString();
  const rawPlatform = searchParams.get("platform");
  const platform = rawPlatform === "douyin" || rawPlatform === "xiaohongshu"
    ? rawPlatform
    : undefined;
  const accountCandidate = accounts.find(
    (account) => account.account_id === searchParams.get("account"),
  );
  const accountId = accountCandidate && accountCandidate.platform === platform
    ? accountCandidate.account_id
    : undefined;
  const rawMethod = searchParams.get("method");
  const captureTaskId = searchParams.get("capture_task_id") ?? undefined;
  const batchId = searchParams.get("batch_id") ?? undefined;
  const method = captureTaskId
    ? "extension"
    : rawMethod && METHOD_VALUES.has(rawMethod as ImportMethod)
      ? rawMethod as ImportMethod
      : undefined;
  const rawHistoryPage = Number(searchParams.get("history_page") ?? "1");
  const historyPage = Number.isSafeInteger(rawHistoryPage) && rawHistoryPage > 0
    ? rawHistoryPage
    : 1;
  const [state, setState] = useState<ImportCenterState>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    loadImportHistory(
      workspaceId,
      { platform, accountId, page: historyPage },
      controller.signal,
    )
      .then((history) => setState({
        status: "ready",
        history,
        queryKey: searchKey,
      }))
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) {
          setState({
            status: "failed",
            queryKey: searchKey,
            message: caught instanceof Error
              ? caught.message
              : "导入历史加载失败",
          });
        }
      });
    return () => controller.abort();
  }, [accountId, historyPage, platform, searchKey, workspaceId]);

  if (
    !context
    || state.status === "loading"
    || state.queryKey !== searchKey
  ) {
    return (
      <GuidedPageShell pageId="imports">
        <Skeleton label="正在加载数据导入中心" />
      </GuidedPageShell>
    );
  }
  if (state.status === "failed") {
    return (
      <GuidedPageShell pageId="imports">
        <ErrorState
          description="导入历史暂时无法读取；已保存数据和当前筛选不会受到影响。"
          title="数据导入加载失败"
        />
      </GuidedPageShell>
    );
  }

  function replaceQuery(change: Record<string, string | undefined>) {
    const query = new URLSearchParams(searchKey);
    for (const [key, value] of Object.entries(change)) {
      if (value) query.set(key, value);
      else query.delete(key);
    }
    router.push(`${pathname}?${query}`);
  }

  return (
    <ImportCenter
      accountId={accountId}
      accounts={accounts}
      batchId={batchId}
      captureTaskId={captureTaskId}
      history={state.history}
      method={method}
      onHistoryPageChange={(page) => replaceQuery({
        history_page: String(page),
      })}
      onMethodChange={(nextMethod) => replaceQuery({
        method: nextMethod,
        capture_task_id: undefined,
        batch_id: undefined,
      })}
      onScopeChange={(scope) => {
        if (
          method
          && typeof window !== "undefined"
          && !window.confirm("切换范围会清除未提交的映射和修正，是否继续？")
        ) return;
        replaceQuery({
          platform: scope.platform,
          account: scope.accountId,
          history_page: "1",
          capture_task_id: undefined,
          batch_id: undefined,
        });
      }}
      platform={platform}
      role={context.role}
      workspaceId={workspaceId}
    />
  );
}
