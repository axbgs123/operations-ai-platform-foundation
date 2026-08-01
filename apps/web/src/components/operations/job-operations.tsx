"use client";

import { useEffect, useState } from "react";

import { GuidedPageHeader } from "@/components/workbench/guided-page-header";
import { useExperiencePreferences } from "@/components/workbench/experience-preferences-context";
import { copyForMode, type ModeAwareCopy } from "@/components/workbench/operator-copy-catalog";
import {
  listOperationalTasks,
  mutateOperationalTask,
  readOperationsAccess,
  readOperationsReadiness,
  type OperationalTask,
  type ReadinessResponse,
} from "@/lib/operations-api";

type WorkspaceRole = "admin" | "editor" | "viewer" | "demo";

type Props = {
  workspaceId: string;
  role?: WorkspaceRole;
};

const same = (text: string): ModeAwareCopy => ({
  simple: text,
  professional: text,
});

const statusLabels: Record<string, ModeAwareCopy> = {
  queued: same("排队中"),
  pending: same("等待中"),
  running: same("执行中"),
  retrying: same("等待重试"),
  succeeded: same("已完成"),
  failed: same("失败"),
  cancelled: same("已取消"),
  dead_letter: {
    simple: "多次尝试仍失败，需要管理员处理",
    professional: "dead_letter",
  },
  compensation_required: {
    simple: "自动清理没有完成，需要管理员处理",
    professional: "compensation_required",
  },
  configuration_required: {
    simple: "还没有完成所需配置",
    professional: "configuration_required",
  },
  provider_outcome_unknown: {
    simple: "模型服务是否已经计费暂时无法确认，请勿直接重复提交",
    professional: "provider_outcome_unknown",
  },
};

const compensationCopy: ModeAwareCopy = {
  simple: "自动清理没有完成，需要管理员处理。普通取消不会完成清理，请联系管理员检查暂存对象。",
  professional: "需要人工补偿：普通取消不会覆盖补偿状态，请由管理员检查暂存对象。",
};

const deadLetterCopy: ModeAwareCopy = {
  simple: "多次尝试仍失败，需要管理员处理。请联系管理员检查失败原因后再安全重试。",
  professional: "死信任务：请检查安全错误码与依赖状态后发起受控重试。",
};

const dependencyLabels: Record<string, string> = {
  postgresql: "PostgreSQL",
  postgres: "PostgreSQL",
  redis: "Redis",
  s3: "S3",
  storage: "S3",
};

export function JobOperations({ workspaceId, role: suppliedRole }: Props) {
  const { copyMode } = useExperiencePreferences();
  const [tasks, setTasks] = useState<OperationalTask[]>([]);
  const [readiness, setReadiness] = useState<ReadinessResponse | null>(null);
  const [taskType, setTaskType] = useState("");
  const [status, setStatus] = useState("");
  const [createdAfter, setCreatedAfter] = useState("");
  const [createdBefore, setCreatedBefore] = useState("");
  const [offset, setOffset] = useState(0);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [total, setTotal] = useState(0);
  const [loadedRole, setLoadedRole] = useState<WorkspaceRole | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const role = suppliedRole ?? loadedRole;
  const canRead = role === "admin" || role === "editor";
  const canOperate = role === "admin";
  const displayState = (value: string) => (
    statusLabels[value] ? copyForMode(statusLabels[value], copyMode) : value
  );

  useEffect(() => {
    if (suppliedRole) {
      return;
    }
    let active = true;
    readOperationsAccess(workspaceId)
      .then((access) => {
        if (active) setLoadedRole(access.role);
      })
      .catch((caught: unknown) => {
        if (active) {
          setError(caught instanceof Error ? caught.message : "权限加载失败");
          setLoadedRole("viewer");
        }
      });
    return () => {
      active = false;
    };
  }, [suppliedRole, workspaceId]);

  useEffect(() => {
    let active = true;
    if (!canRead) {
      return () => {
        active = false;
      };
    }
    Promise.allSettled([
      listOperationalTasks(workspaceId, {
        taskType,
        status,
        createdAfter: createdAfter || undefined,
        createdBefore: createdBefore || undefined,
        offset,
      }),
      readOperationsReadiness(),
    ])
      .then(([taskResult, readinessResult]) => {
        if (!active) return;
        if (taskResult.status === "fulfilled") {
          setTasks(taskResult.value.items);
          setNextOffset(taskResult.value.next_offset);
          setTotal(taskResult.value.total);
        } else {
          setError(
            taskResult.reason instanceof Error
              ? taskResult.reason.message
              : "后台任务加载失败",
          );
        }
        if (readinessResult.status === "fulfilled") {
          setReadiness(readinessResult.value);
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [
    canRead,
    createdAfter,
    createdBefore,
    offset,
    status,
    taskType,
    workspaceId,
  ]);

  async function act(task: OperationalTask, action: "cancel" | "retry") {
    const key = `${task.task_id}:${action}`;
    setBusy(key);
    setError("");
    setMessage("");
    try {
      const updated = await mutateOperationalTask(
        workspaceId,
        task,
        action,
        sessionStorage.getItem("workspace_csrf") ?? "",
        `${action}:${task.task_id}`,
      );
      setTasks((current) =>
        current.map((item) =>
          item.task_id === updated.task_id ? updated : item,
        ),
      );
      setMessage(action === "cancel" ? "取消请求已记录" : "受控重试已创建");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "后台任务操作失败");
    } finally {
      setBusy("");
    }
  }

  if (role === null) {
    return (
      <div className="space-y-6">
        <GuidedPageHeader pageId="jobs" />
        <p role="status">正在加载运维权限…</p>
      </div>
    );
  }

  if (!canRead) {
    return (
      <div className="space-y-6">
        <GuidedPageHeader pageId="jobs" />
        <p className="rounded-2xl border border-amber-800 bg-amber-950/30 p-6 text-amber-200">
          当前角色没有运维任务查看权限。
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <GuidedPageHeader pageId="jobs" />

      <section
        aria-label="依赖就绪状态"
        className="rounded-xl border bg-white p-4"
      >
        <h2 className="font-semibold">
          {copyMode === "simple" ? "系统依赖状态" : "Readiness"}
        </h2>
        <p className="mt-2 text-sm text-[var(--text-secondary)]">
          {readiness?.status === "ready" ? "依赖已就绪" : "依赖未全部就绪"}
        </p>
        <div className="mt-2 flex flex-wrap gap-2 text-xs">
          {readiness?.components.map((component) => (
            <span
              className="rounded-full border bg-slate-50 px-3 py-1"
              key={component.name}
            >
              {dependencyLabels[component.name.toLowerCase()] ?? component.name}
              ：{component.status === "ready" ? "已就绪" : "未就绪"}
              {component.error_code && copyMode === "professional"
                ? ` · ${component.error_code}`
                : ""}
            </span>
          ))}
        </div>
      </section>

      <section className="flex flex-wrap gap-3" aria-label="任务筛选">
        <label>
          <span className="sr-only">任务类型</span>
          <select
            aria-label="任务类型"
            className="rounded-lg border bg-white px-3 py-2"
            onChange={(event) => {
              setTaskType(event.target.value);
              setOffset(0);
            }}
            value={taskType}
          >
            <option value="">全部类型</option>
            <option value="analysis">分析</option>
            <option value="generation">生成</option>
            <option value="export">导出</option>
            <option value="restore">恢复</option>
            <option value="extension_capture">扩展采集</option>
            <option value="risk_scan">风控扫描</option>
          </select>
        </label>
        <label>
          <span className="sr-only">任务状态</span>
          <select
            aria-label="任务状态"
            className="rounded-lg border bg-white px-3 py-2"
            onChange={(event) => {
              setStatus(event.target.value);
              setOffset(0);
            }}
            value={status}
          >
            <option value="">全部状态</option>
            <option value="running">执行中</option>
            <option value="failed">失败</option>
            <option value="cancelled">已取消</option>
          </select>
        </label>
        <label>
          <span className="sr-only">开始时间</span>
          <input
            aria-label="开始时间"
            className="rounded-lg border bg-white px-3 py-2"
            onChange={(event) => {
              setCreatedAfter(event.target.value);
              setOffset(0);
            }}
            type="datetime-local"
            value={createdAfter}
          />
        </label>
        <label>
          <span className="sr-only">结束时间</span>
          <input
            aria-label="结束时间"
            className="rounded-lg border bg-white px-3 py-2"
            onChange={(event) => {
              setCreatedBefore(event.target.value);
              setOffset(0);
            }}
            type="datetime-local"
            value={createdBefore}
          />
        </label>
      </section>

      {loading ? <p>正在加载后台任务…</p> : null}
      {message ? <p className="text-emerald-300">{message}</p> : null}
      {error ? (
        <p role="alert" className="rounded-xl bg-rose-950/50 p-4 text-rose-200">
          {error}
        </p>
      ) : null}
      {!loading && tasks.length === 0 ? (
        <p className="rounded-xl border border-dashed border-slate-700 p-6">
          没有符合筛选条件的任务
        </p>
      ) : null}

      <section className="space-y-3" aria-label="后台任务列表">
        {tasks.map((task) => {
          const compensation =
            task.status === "compensation_required" ||
            task.phase === "compensation_required";
          const deadLetter = task.status === "dead_letter";
          return (
            <article
              className="rounded-xl border bg-white p-5"
              key={`${task.task_type}:${task.task_id}`}
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="font-semibold">{task.task_type}</h2>
                  <p className="mt-1 text-sm text-slate-400">
                    阶段：{task.phase ? displayState(task.phase) : "未报告"} · 重试 {task.retry_count}/
                    {task.max_retries}
                  </p>
                </div>
                <span className="rounded-full bg-slate-950 px-3 py-1 text-sm">
                  {displayState(task.status)}
                </span>
              </div>
              <dl className="mt-4 grid gap-2 text-sm sm:grid-cols-3">
                <div>
                  <dt className="text-slate-500">创建时间</dt>
                  <dd>{task.created_at}</dd>
                </div>
                <div>
                  <dt className="text-slate-500">更新时间</dt>
                  <dd>{task.updated_at}</dd>
                </div>
                <div>
                  <dt className="text-slate-500">
                    {copyMode === "simple" ? "失败原因编号" : "安全错误码"}
                  </dt>
                  <dd>{task.error_code ?? "无"}</dd>
                </div>
              </dl>
              {compensation ? (
                <p className="mt-4 rounded-xl bg-amber-950/50 p-3 text-amber-200">
                  {copyForMode(compensationCopy, copyMode)}
                </p>
              ) : null}
              {deadLetter ? (
                <p className="mt-4 rounded-xl bg-rose-950/50 p-3 text-rose-200">
                  {copyForMode(deadLetterCopy, copyMode)}
                </p>
              ) : null}
              {canOperate ? (
                <div className="mt-4 flex gap-2">
                  {task.cancelable ? (
                    <button
                      disabled={busy === `${task.task_id}:cancel`}
                      onClick={() => void act(task, "cancel")}
                      type="button"
                    >
                      取消任务
                    </button>
                  ) : null}
                  {task.retryable ? (
                    <button
                      disabled={busy === `${task.task_id}:retry`}
                      onClick={() => void act(task, "retry")}
                      type="button"
                    >
                      受控重试
                    </button>
                  ) : null}
                </div>
              ) : null}
            </article>
          );
        })}
      </section>
      <nav className="flex items-center gap-3" aria-label="任务分页">
        <button
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - 25))}
          type="button"
        >
          上一页
        </button>
        <span className="text-sm text-slate-400">
          {total === 0 ? 0 : offset + 1}–{Math.min(offset + tasks.length, total)} /{" "}
          {total}
        </span>
        <button
          disabled={nextOffset === null}
          onClick={() => nextOffset !== null && setOffset(nextOffset)}
          type="button"
        >
          下一页
        </button>
      </nav>
    </div>
  );
}
