"use client";

import { FormEvent, useEffect, useState } from "react";

import { readOperationsAccess } from "@/lib/operations-api";
import {
  getPublicProvider,
  savePublicProvider,
  testPublicProvider,
  type PublicProviderConfig,
} from "@/lib/public-data-api";
import {
  ErrorState,
  PageHeader,
  Panel,
  PermissionNotice,
  Skeleton,
  StatusBadge,
} from "@/components/workbench/ui";

type WorkspaceRole = "admin" | "editor" | "viewer" | "demo";

const control =
  "mt-2 w-full rounded-xl border border-[var(--border)] bg-white px-4 py-3 text-[var(--text-primary)]";

export function PublicDataProviderSettings({ workspaceId }: { workspaceId: string }) {
  const [role, setRole] = useState<WorkspaceRole | null>(null);
  const [config, setConfig] = useState<PublicProviderConfig | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [region, setRegion] = useState<"china" | "global">("china");
  const [dailyLimit, setDailyLimit] = useState(500);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    let active = true;
    Promise.all([getPublicProvider(workspaceId), readOperationsAccess(workspaceId)])
      .then(([saved, access]) => {
        if (!active) return;
        setConfig(saved);
        setRole(access.role as WorkspaceRole);
        if (saved) {
          setRegion(saved.endpoint_region);
          setDailyLimit(saved.daily_request_limit);
        }
      })
      .catch(() => {
        if (active) setLoadError(true);
      });
    return () => {
      active = false;
    };
  }, [workspaceId]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setMessage("");
    try {
      const saved = await savePublicProvider(
        workspaceId,
        sessionStorage.getItem("workspace_csrf") ?? "",
        {
          api_key: apiKey,
          endpoint_region: region,
          daily_request_limit: dailyLimit,
        },
      );
      setConfig(saved);
      setApiKey("");
      setMessage("已保存。密钥不会再次显示，请继续测试连接。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存失败");
    } finally {
      setPending(false);
    }
  }

  async function testConnection() {
    setPending(true);
    setMessage("");
    try {
      const result = await testPublicProvider(
        workspaceId,
        sessionStorage.getItem("workspace_csrf") ?? "",
      );
      const latest = await getPublicProvider(workspaceId);
      setConfig(latest);
      setMessage(
        result.connected
          ? "连接成功，可以在内容详情中绑定抖音或小红书作品。"
          : `连接失败：${result.safe_error_code ?? "请检查密钥和网络"}`,
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "连接测试失败");
    } finally {
      setPending(false);
    }
  }

  if (loadError) {
    return <ErrorState description="请刷新页面后重试。" title="采集配置加载失败" />;
  }
  if (role === null) return <Skeleton label="正在加载公开数据采集设置" />;

  const isAdmin = role === "admin";
  return (
    <div className="space-y-6">
      <PageHeader
        description="接入 TikHub 后，可自动回收作品数据，也可监测对标账号和分析公开评论。"
        title="公开数据采集"
      />
      <Panel
        description="当前只读取公开作品数据，不需要抖音或小红书 Cookie，也不会自动发布内容。"
        title="TikHub 连接"
      >
        <div className="mb-5 flex flex-wrap items-center gap-3">
          <StatusBadge
            tone={config?.status === "verified" ? "success" : "warning"}
          >
            {config?.status === "verified" ? "连接正常" : "尚未连接"}
          </StatusBadge>
          <span className="text-sm text-[var(--text-secondary)]">
            {config
              ? `接口区域：${config.endpoint_region === "china" ? "中国" : "海外"} · 今日已用 ${config.daily_requests_used}/${config.daily_request_limit} 次`
              : "保存密钥并测试后才能自动采集"}
          </span>
        </div>
        {!isAdmin ? (
          <PermissionNotice
            currentRole={role}
            description="只有管理员可以保存或更换 TikHub 密钥。"
            requiredRole="管理员"
          />
        ) : (
          <form className="space-y-4" onSubmit={save}>
            <label className="block text-sm font-medium">
              TikHub API Key
              <input
                autoComplete="off"
                className={control}
                onChange={(event) => setApiKey(event.target.value)}
                placeholder={config ? "输入新密钥会替换原密钥" : "粘贴 TikHub API Key"}
                required
                type="password"
                value={apiKey}
              />
            </label>
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="block text-sm font-medium">
                接口区域
                <select
                  className={control}
                  onChange={(event) => setRegion(event.target.value as "china" | "global")}
                  value={region}
                >
                  <option value="china">中国大陆线路</option>
                  <option value="global">海外线路</option>
                </select>
              </label>
              <label className="block text-sm font-medium">
                每日最多调用次数
                <input
                  className={control}
                  max={100000}
                  min={1}
                  onChange={(event) => setDailyLimit(Number(event.target.value))}
                  type="number"
                  value={dailyLimit}
                />
              </label>
            </div>
            <div className="flex flex-wrap gap-3">
              <button
                className="rounded-lg bg-[var(--brand)] px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
                disabled={pending}
                type="submit"
              >
                {pending ? "处理中…" : config ? "更换密钥" : "保存密钥"}
              </button>
              <button
                className="rounded-lg border border-[var(--border)] bg-white px-4 py-2.5 text-sm font-semibold disabled:opacity-50"
                disabled={pending || !config}
                onClick={testConnection}
                type="button"
              >
                测试连接
              </button>
            </div>
          </form>
        )}
        {message ? <p className="mt-4 text-sm" role="status">{message}</p> : null}
      </Panel>
      <Panel title="怎么使用">
        <ol className="list-decimal space-y-2 pl-5 text-sm leading-6">
          <li>保存 API Key，并点击“测试连接”。</li>
          <li>打开一条内容，在“数据快照”中粘贴公开作品链接。</li>
          <li>系统按 1 小时、24 小时、3 天、7 天自动采集，也可以随时手动采集。</li>
          <li>采集结果直接进入数据快照，可继续用于内容分析。</li>
          <li>前往“热点创作 → 对标、评论与日报”，添加对标账号或分析公开评论。</li>
        </ol>
      </Panel>
    </div>
  );
}
