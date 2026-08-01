"use client";

import Link from "next/link";
import { useState } from "react";

import { GuidedPageHeader } from "@/components/workbench/guided-page-header";
import { useExperiencePreferences } from "@/components/workbench/experience-preferences-context";
import { DesktopOnlyNotice, Panel, StatusBadge } from "@/components/workbench/ui";
import { useWorkbenchShellContext } from "@/components/workbench/workspace-shell";
import {
  confirmWorkspaceDeletion,
  readWorkspaceDeletionImpact,
  requestWorkspaceDeletionConfirmation,
  type WorkspaceDeletionConfirmation,
  type WorkspaceDeletionImpact,
} from "@/lib/export-api";

import { SettingsNav } from "./settings-nav";

type Role = "admin" | "editor" | "viewer";

export function WorkspaceSettings({
  workspaceId,
  role: suppliedRole,
}: {
  workspaceId: string;
  role?: Role;
}) {
  const context = useWorkbenchShellContext();
  const { copyMode } = useExperiencePreferences();
  const accounts = context?.accounts ?? [];
  const role = suppliedRole ?? context?.role;
  const [impact, setImpact] = useState<WorkspaceDeletionImpact | null>(null);
  const [confirmation, setConfirmation] =
    useState<WorkspaceDeletionConfirmation | null>(null);
  const [deletionNotice, setDeletionNotice] = useState("");
  const [deletionError, setDeletionError] = useState("");
  const [deletionBusy, setDeletionBusy] = useState(false);
  const canDeleteWorkspace = role === "admin";

  async function loadDeletionImpact() {
    setDeletionBusy(true);
    setDeletionError("");
    try {
      setImpact(await readWorkspaceDeletionImpact(workspaceId));
      setConfirmation(null);
      setDeletionNotice(
        copyMode === "simple"
          ? "删除前影响检查已加载；尚未申请或执行删除。"
          : "影响预览已加载；尚未申请或执行删除。",
      );
    } catch (error) {
      setDeletionError(
        error instanceof Error
          ? error.message
          : copyMode === "simple" ? "删除前影响检查失败" : "影响预览失败",
      );
    } finally {
      setDeletionBusy(false);
    }
  }

  async function requestDeletion() {
    setDeletionBusy(true);
    setDeletionError("");
    try {
      setConfirmation(
        await requestWorkspaceDeletionConfirmation(
          workspaceId,
          sessionStorage.getItem("workspace_csrf") ?? "",
        ),
      );
      setDeletionNotice("一次性确认已签发，仅保存在当前页面内存；仍未执行删除。");
    } catch (error) {
      setDeletionError(error instanceof Error ? error.message : "申请确认失败");
    } finally {
      setDeletionBusy(false);
    }
  }

  async function confirmDeletion() {
    if (!confirmation) return;
    setDeletionBusy(true);
    setDeletionError("");
    try {
      const job = await confirmWorkspaceDeletion(
        workspaceId,
        confirmation.confirmation_token,
        sessionStorage.getItem("workspace_csrf") ?? "",
      );
      setConfirmation(null);
      setDeletionNotice(`删除任务已受控提交：${job.status}。残留检查完成前不视为成功。`);
    } catch (error) {
      setDeletionError(error instanceof Error ? error.message : "删除确认失败");
    } finally {
      setDeletionBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <GuidedPageHeader pageId="settings" />
      <SettingsNav workspaceId={workspaceId} />
      <Panel title="工作区概览">
        <dl className="grid gap-3 text-sm sm:grid-cols-3">
          <div><dt>工作区名称</dt><dd>{context?.workspace_name ?? "正在加载"}</dd></div>
          <div><dt>当前角色</dt><dd>{context?.role ?? "正在加载"}</dd></div>
          <div><dt>账号数量</dt><dd>{accounts.length}</dd></div>
          <div><dt>内容数量</dt><dd>当前安全读模型未提供</dd></div>
          <div><dt>任务安全状态</dt><dd>{context?.failed_task_count ? `${context.failed_task_count} 个失败任务` : "无已知失败任务"}</dd></div>
          <div><dt>工作区边界</dt><dd>私有工作区；Demo 数据不会进入此处</dd></div>
          <div><dt>产品版本</dt><dd>workbench-2026.07</dd></div>
        </dl>
      </Panel>
      <section className="grid gap-4 lg:grid-cols-2">
        <Panel title="成员与邀请码">
          <p className="text-sm text-[var(--text-secondary)]">
            {copyMode === "simple"
              ? "邀请码只在创建时显示一次。请立即交给对应成员，不要发到公开群或截图保存到公共位置。"
              : "邀请码只在创建时显示一次，服务端仅保存强哈希；不可找回原邀请码。"}
          </p>
          <Link className="mt-4 inline-block text-sm font-semibold text-blue-700" href={`/workspaces/${workspaceId}/settings/members`}>
            管理成员与独立邀请码
          </Link>
        </Panel>
        <Panel title="平台账号配置">
          <div className="space-y-2">
            {accounts.map((account) => (
              <p className="rounded-lg bg-slate-50 p-3 text-sm" key={account.account_id}>
                <StatusBadge tone="info">{account.platform === "douyin" ? "抖音" : "小红书"}</StatusBadge>
                <span className="ml-2">{account.name}</span>
              </p>
            ))}
          </div>
          <Link className="mt-4 inline-block text-sm font-semibold text-blue-700" href={`/workspaces/${workspaceId}/accounts`}>
            查看账号配置与版本
          </Link>
        </Panel>
      </section>
      <Panel title="指标、目标与基准">
        <p className="text-sm leading-6 text-[var(--text-secondary)]">
          平台默认指标、工作区自定义指标、权重和动态基准范围由服务端版本化管理。前端不自行计算分位、权重或样本门槛。
        </p>
        <p className="mt-2 text-sm">范围可使用最近 N 条、时间范围或全部历史；当前生效版本以账号配置页为准。</p>
      </Panel>
      <Panel title="模型配置与预算">
        <div className="flex flex-wrap gap-2">
          <StatusBadge tone="warning">
            {copyMode === "simple"
              ? "试用状态，真实效果和费用尚未完成验收"
              : "Catalog experimental"}
          </StatusBadge>
          <StatusBadge tone="neutral">真实验收 not_run</StatusBadge>
          <StatusBadge tone="info">Demo 仅 Mock</StatusBadge>
        </div>
        <p className="mt-3 text-sm text-[var(--text-secondary)]">
          {copyMode === "simple"
            ? "密钥保存后不会再次显示；更换密钥需要重新输入。真实调用可能产生费用；没有设置每日上限时，系统不会允许调用。"
            : "API Key 不回显，不显示密文、密钥片段或 Provider Workspace ID；未配置预算时真实调用默认拒绝。"}
        </p>
        <div className="mt-4 md:hidden">
          <DesktopOnlyNotice action="模型密钥和预算配置" />
        </div>
        <Link className="mt-4 hidden text-sm font-semibold text-blue-700 md:inline-block" href={`/workspaces/${workspaceId}/settings/models`}>
          打开模型与预算配置
        </Link>
      </Panel>
      <Panel title="保留策略">
        <div className="flex flex-wrap gap-2">
          <StatusBadge tone="neutral">immediate</StatusBadge>
          <StatusBadge tone="info">scheduled</StatusBadge>
          <StatusBadge tone="warning">evidence</StatusBadge>
        </div>
        <p className="mt-3 text-sm text-[var(--text-secondary)]">
          {copyMode === "simple"
            ? "因审计或关联资料要求而保留的内容暂时不能删除；只有管理员能修改保留规则。"
            : "Evidence 会阻止普通清理；策略版本、purge_at、原因和关联资源均以服务端记录为准，仅管理员可修改。"}
        </p>
        <div className="mt-4 md:hidden">
          <DesktopOnlyNotice action="大型保留策略修改" />
        </div>
      </Panel>
      <Panel title="危险操作">
        <p className="text-sm leading-6 text-[var(--text-secondary)]">
          {copyMode === "simple"
            ? "永久删除工作区不会在回收站中进行。先查看会删除哪些内容，再申请一次性确认并最终确认；完成残留检查前不会显示删除成功。"
            : "工作区删除与普通内容回收站分离。流程固定为：影响预览 → 服务端签发短期一次性确认 → 再次确认 → 残留检查。确认令牌不得进入 URL、本地存储或日志。"}
        </p>
        <p className="mt-3 text-sm text-red-800">
          未完成数据、向量、对象、缓存和任务残留检查时，绝不显示删除成功。
        </p>
        <div className="mt-4 md:hidden">
          <DesktopOnlyNotice action="工作区删除和二次确认" />
        </div>
        {canDeleteWorkspace ? (
          <div className="mt-4 hidden space-y-3 md:block">
            <button
              className="rounded-lg border border-red-700 px-4 py-2 text-sm font-semibold text-red-800"
              disabled={deletionBusy}
              onClick={() => void loadDeletionImpact()}
              type="button"
            >
              第一步：查看删除影响
            </button>
            {impact ? (
              <dl className="grid gap-2 rounded-lg bg-red-50 p-4 text-sm sm:grid-cols-3">
                <div><dt>结构化记录</dt><dd>{impact.structured_records}</dd></div>
                <div><dt>资产</dt><dd>{impact.assets}</dd></div>
                <div><dt>向量</dt><dd>{impact.vectors}</dd></div>
                <div><dt>暂存任务</dt><dd>{impact.staging_tasks}</dd></div>
                <div><dt>证据保留对象</dt><dd>{impact.evidence_retained_objects}</dd></div>
                <div><dt>需补偿任务</dt><dd>{impact.compensation_required_jobs}</dd></div>
              </dl>
            ) : null}
            {impact && !confirmation ? (
              <button
                className="rounded-lg border border-red-700 px-4 py-2 text-sm font-semibold text-red-800"
                disabled={deletionBusy}
                onClick={() => void requestDeletion()}
                type="button"
              >
                第二步：申请短期一次性确认
              </button>
            ) : null}
            {confirmation ? (
              <div className="rounded-lg border border-red-700 p-4">
                <p className="text-sm">
                  确认于 {confirmation.expires_at} 过期；令牌不显示、不写 URL 或存储。
                </p>
                <button
                  className="mt-3 rounded-lg bg-red-700 px-4 py-2 text-sm font-semibold text-white"
                  disabled={deletionBusy}
                  onClick={() => void confirmDeletion()}
                  type="button"
                >
                  最终确认删除工作区
                </button>
              </div>
            ) : null}
            {deletionNotice ? <p role="status">{deletionNotice}</p> : null}
            {deletionError ? <p className="text-red-800" role="alert">{deletionError}</p> : null}
          </div>
        ) : (
          <p className="mt-3 text-sm">只有管理员可以发起工作区删除。</p>
        )}
      </Panel>
    </div>
  );
}
