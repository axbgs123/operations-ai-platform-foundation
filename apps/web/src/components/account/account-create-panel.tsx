"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { createAccount } from "@/lib/account-api";

import { Panel } from "@/components/workbench/ui";

type Platform = "douyin" | "xiaohongshu";

const DEFAULT_ACCOUNT_CONFIGURATION = {
  objectives: ["提升内容表现"],
  metric_weights: { views: 1 },
  benchmark_sample_size: 30,
} as const;

export function AccountCreatePanel({ workspaceId }: { workspaceId: string }) {
  const router = useRouter();
  const [platform, setPlatform] = useState<Platform>("douyin");
  const [name, setName] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedName = name.trim();
    if (!normalizedName || pending) return;

    setPending(true);
    setError("");
    try {
      const account = await createAccount(
        workspaceId,
        sessionStorage.getItem("workspace_csrf") ?? "",
        {
          platform,
          name: normalizedName,
          objectives: [...DEFAULT_ACCOUNT_CONFIGURATION.objectives],
          metric_weights: { ...DEFAULT_ACCOUNT_CONFIGURATION.metric_weights },
          benchmark_sample_size:
            DEFAULT_ACCOUNT_CONFIGURATION.benchmark_sample_size,
        },
      );
      const query = new URLSearchParams({
        platform: account.platform,
        account: account.id,
      });
      router.push(
        `/workspaces/${workspaceId}/accounts/${account.id}?${query.toString()}`,
      );
    } catch {
      setError("账号创建失败，请检查信息后重试。");
      setPending(false);
    }
  }

  return (
    <Panel
      description="先建立一个平台账号，之后再导入作品和运营数据。目标和比较范围会使用推荐默认值，创建后可以继续调整。"
      title="创建平台账号"
    >
      <form className="grid gap-4 md:grid-cols-2" onSubmit={(event) => void submit(event)}>
        <label className="space-y-2 text-sm font-medium">
          <span>所属平台</span>
          <select
            aria-label="所属平台"
            className="w-full px-3 py-2.5"
            disabled={pending}
            onChange={(event) => setPlatform(event.target.value as Platform)}
            value={platform}
          >
            <option value="douyin">抖音</option>
            <option value="xiaohongshu">小红书</option>
          </select>
        </label>
        <label className="space-y-2 text-sm font-medium">
          <span>账号名称</span>
          <input
            aria-label="账号名称"
            autoComplete="off"
            className="w-full px-3 py-2.5"
            disabled={pending}
            maxLength={120}
            onChange={(event) => setName(event.target.value)}
            placeholder="例如：品牌抖音主账号"
            required
            value={name}
          />
        </label>
        <div className="md:col-span-2">
          <p className="text-sm leading-6 text-[var(--text-secondary)]">
            默认使用最近 30 条作品作比较，并先关注播放表现；后续可在账号配置中修改。
          </p>
          {error ? (
            <p className="mt-2 text-sm font-semibold text-red-800" role="alert">
              {error}
            </p>
          ) : null}
          <button
            className="mt-4 rounded-lg bg-[var(--brand)] px-4 py-2.5 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
            disabled={pending || !name.trim()}
            type="submit"
          >
            {pending ? "正在创建账号" : "创建账号"}
          </button>
        </div>
      </form>
    </Panel>
  );
}
