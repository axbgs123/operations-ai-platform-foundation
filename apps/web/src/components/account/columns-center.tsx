"use client";

import { useEffect, useState, type ReactElement } from "react";
import { useSearchParams } from "next/navigation";

import {
  loadColumnCampaigns,
  loadEffectiveAccountConfiguration,
  loadEffectiveColumnConfiguration,
  restoreColumnDefaults,
  type EffectiveAccountConfiguration,
} from "@/lib/account-api";
import {
  loadWorkbenchContext,
  type WorkbenchContext,
} from "@/lib/workbench-api";
import {
  loadEffectiveStyle,
  type EffectiveStyleData,
} from "@/lib/style-api";
import {
  DataTableFrame,
  EmptyState,
  ErrorState,
  PageHeader,
  Skeleton,
  StatusBadge,
} from "@/components/workbench/ui";


export type ColumnFieldView = {
  label: string;
  accountDefault: string;
  effectiveValue: string;
  mode: "inherited" | "temporary_override" | "unavailable";
};

export type ColumnWorkbenchItem = {
  id: string;
  accountId: string;
  accountName: string;
  platform: "douyin" | "xiaohongshu";
  name: string;
  kind: "column" | "campaign";
  startsAt: string | null;
  endsAt: string | null;
  status: "scheduled" | "active" | "expired";
  overrideCount: number;
  currentVersion: string;
  fields: ColumnFieldView[];
};

export function filterColumnsByScope(
  items: ColumnWorkbenchItem[],
  platform: string | null,
  accountId: string | null,
): ColumnWorkbenchItem[] {
  if (platform !== null && platform !== "douyin" && platform !== "xiaohongshu") {
    return [];
  }
  return items.filter((item) =>
    (platform === null || item.platform === platform)
    && (accountId === null || item.accountId === accountId)
  );
}

const platformLabel = {
  douyin: "抖音",
  xiaohongshu: "小红书",
} as const;

function configText(
  config: EffectiveAccountConfiguration,
  field: "objectives" | "metric_weights" | "benchmark",
): string {
  if (field === "objectives") {
    return config.objective_profile.objectives.join("、");
  }
  if (field === "metric_weights") {
    return Object.entries(config.objective_profile.metric_weights)
      .map(([key, value]) => `${key} ${Math.round(value * 100)}%`)
      .join("、");
  }
  return `最近 ${config.benchmark_profile.sample_size} 条`;
}

function columnStatus(
  startsAt: string | null,
  endsAt: string | null,
  now = Date.now(),
): ColumnWorkbenchItem["status"] {
  if (startsAt && new Date(startsAt).getTime() > now) return "scheduled";
  if (endsAt && new Date(endsAt).getTime() < now) return "expired";
  return "active";
}

function formatWindow(startsAt: string | null, endsAt: string | null): string {
  if (!startsAt && !endsAt) return "长期有效";
  const format = (value: string) => new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeZone: "Asia/Shanghai",
  }).format(new Date(value));
  return `${startsAt ? format(startsAt) : "立即"} — ${endsAt ? format(endsAt) : "长期"}`;
}

export function buildColumnFieldViews(
  item: {
    objective_profile_id: string | null;
    benchmark_profile_id: string | null;
  },
  accountDefault: EffectiveAccountConfiguration,
  effective: EffectiveAccountConfiguration,
  accountStyle: EffectiveStyleData | null,
  effectiveStyle: EffectiveStyleData | null,
): ColumnFieldView[] {
  const objectiveOverride = item.objective_profile_id !== null;
  const benchmarkOverride = item.benchmark_profile_id !== null;
  return [
    {
      label: "运营目标",
      accountDefault: configText(accountDefault, "objectives"),
      effectiveValue: configText(effective, "objectives"),
      mode: objectiveOverride ? "temporary_override" : "inherited",
    },
    {
      label: "指标权重",
      accountDefault: configText(accountDefault, "metric_weights"),
      effectiveValue: configText(effective, "metric_weights"),
      mode: objectiveOverride ? "temporary_override" : "inherited",
    },
    {
      label: "动态基准范围",
      accountDefault: configText(accountDefault, "benchmark"),
      effectiveValue: configText(effective, "benchmark"),
      mode: benchmarkOverride ? "temporary_override" : "inherited",
    },
    {
      label: "标题、文案和封面风格",
      accountDefault: accountStyle
        ? `账号风格 v${accountStyle.version}`
        : "尚无已确认账号风格",
      effectiveValue: effectiveStyle
        ? `${
          effectiveStyle.source === "column_override"
            ? "栏目风格"
            : "账号风格"
        } v${effectiveStyle.version}`
        : "尚无可用风格版本",
      mode: effectiveStyle?.source === "column_override"
        ? "temporary_override"
        : "inherited",
    },
    {
      label: "生成预设",
      accountDefault: "尚无已配置的账号生成预设",
      effectiveValue: "当前合同未提供栏目级预设覆盖",
      mode: "unavailable",
    },
  ];
}

async function loadColumnItems(
  workspaceId: string,
  context: WorkbenchContext,
): Promise<ColumnWorkbenchItem[]> {
  const groups = await Promise.all(context.accounts.map(async (account) => {
    const [columns, accountDefault, accountStyle] = await Promise.all([
      loadColumnCampaigns(workspaceId, account.account_id),
      loadEffectiveAccountConfiguration(workspaceId, account.account_id),
      loadEffectiveStyle(workspaceId, account.account_id).catch(() => null),
    ]);
    return Promise.all(columns.map(async (item) => {
      const [effective, effectiveStyle] = await Promise.all([
        loadEffectiveColumnConfiguration(
          workspaceId,
          account.account_id,
          item.id,
        ),
        loadEffectiveStyle(
          workspaceId,
          account.account_id,
          item.id,
        ).catch(() => null),
      ]);
      return {
        id: item.id,
        accountId: account.account_id,
        accountName: account.name,
        platform: account.platform,
        name: item.name,
        kind: item.kind,
        startsAt: item.starts_at,
        endsAt: item.ends_at,
        status: columnStatus(item.starts_at, item.ends_at),
        overrideCount: Number(item.objective_profile_id !== null)
          + Number(item.benchmark_profile_id !== null),
        currentVersion: (
          `目标 v${effective.objective_profile.version} · `
          + `基准 v${effective.benchmark_profile.version} · `
          + (
            effectiveStyle
              ? `风格 v${effectiveStyle.version}`
              : "风格未配置"
          )
        ),
        fields: buildColumnFieldViews(
          item,
          accountDefault,
          effective,
          accountStyle,
          effectiveStyle,
        ),
      } satisfies ColumnWorkbenchItem;
    }));
  }));
  return groups.flat().sort((left, right) =>
    `${left.platform}:${left.accountName}:${left.name}`.localeCompare(
      `${right.platform}:${right.accountName}:${right.name}`,
      "zh-CN",
    )
  );
}

export function ColumnsCenter({
  items,
  role,
  onRestoreDefaults,
}: {
  items: ColumnWorkbenchItem[];
  role: WorkbenchContext["role"];
  onRestoreDefaults?: (item: ColumnWorkbenchItem) => void;
}): ReactElement {
  if (!items.length) {
    return (
      <EmptyState
        description="栏目和活动会继承所属账号配置，并可在有效时间内使用临时覆盖。"
        title="还没有栏目或活动"
      />
    );
  }
  const statusLabel = {
    scheduled: "待生效",
    active: "生效中",
    expired: "已结束",
  } as const;
  return (
    <DataTableFrame label="栏目与活动列表">
      <div className="min-w-[900px]">
        <div className="grid grid-cols-[1.3fr_1.2fr_1.2fr_.8fr_.8fr] gap-4 border-b bg-slate-50 px-4 py-3 text-xs font-semibold text-[var(--text-secondary)]">
          <span>栏目/活动</span><span>平台与账号</span><span>有效时间</span><span>状态/覆盖</span><span>版本</span>
        </div>
        {items.map((item) => (
          <article className="border-b p-4 last:border-b-0" key={item.id}>
            <div className="grid grid-cols-[1.3fr_1.2fr_1.2fr_.8fr_.8fr] items-start gap-4 text-sm">
              <div><strong>{item.name}</strong><p className="text-[var(--text-secondary)]">{item.kind === "campaign" ? "活动" : "栏目"}</p></div>
              <div><span>{platformLabel[item.platform]}</span><p>{item.accountName}</p></div>
              <span>{formatWindow(item.startsAt, item.endsAt)}</span>
              <div>
                <StatusBadge tone={item.status === "active" ? "success" : "neutral"}>{statusLabel[item.status]}</StatusBadge>
                <p className="mt-1 text-xs">{item.overrideCount} 项覆盖</p>
              </div>
              <strong>{item.currentVersion}</strong>
            </div>
            <details className="mt-4 rounded-lg border bg-slate-50 p-4" open>
              <summary className="cursor-pointer font-semibold">查看继承与覆盖</summary>
              <div className="mt-4 space-y-3">
                {item.fields.map((field) => (
                  <div className="grid gap-2 rounded-lg bg-white p-3 md:grid-cols-[1fr_1.5fr_1.5fr]" key={field.label}>
                    <strong>{field.label}</strong>
                    <p><span className="block text-xs text-[var(--text-secondary)]">账号默认值</span>{field.accountDefault}</p>
                    <p>
                      <StatusBadge tone={field.mode === "temporary_override" ? "warning" : "neutral"}>
                        {
                          field.mode === "temporary_override"
                            ? "临时覆盖"
                            : field.mode === "unavailable"
                              ? "合同未提供"
                              : "继承账号默认"
                        }
                      </StatusBadge>
                      <span className="mt-1 block">{field.effectiveValue}</span>
                    </p>
                  </div>
                ))}
              </div>
              <div className="mt-3 text-sm text-[var(--text-secondary)]">
                <p>覆盖生效时间：{formatWindow(item.startsAt, item.endsAt)}</p>
                <p className="font-semibold">覆盖结束后恢复账号默认</p>
              </div>
              {role === "viewer" ? (
                <p className="mt-3 text-sm font-semibold">只读查看</p>
              ) : item.overrideCount && onRestoreDefaults ? (
                <button
                  className="mt-3 rounded-lg border px-3 py-2 text-sm font-semibold"
                  onClick={() => onRestoreDefaults(item)}
                  type="button"
                >
                  恢复账号默认
                </button>
              ) : null}
            </details>
          </article>
        ))}
      </div>
    </DataTableFrame>
  );
}

export function ColumnsCenterPage({
  workspaceId,
}: {
  workspaceId: string;
}): ReactElement {
  const searchParams = useSearchParams();
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<
    | { status: "loading" }
    | { status: "ready"; context: WorkbenchContext; items: ColumnWorkbenchItem[] }
    | { status: "failed" }
  >({ status: "loading" });

  useEffect(() => {
    let active = true;
    loadWorkbenchContext(workspaceId)
      .then(async (context) => ({
        context,
        items: await loadColumnItems(workspaceId, context),
      }))
      .then((result) => {
        if (active) setState({ status: "ready", ...result });
      })
      .catch(() => {
        if (active) setState({ status: "failed" });
      });
    return () => { active = false; };
  }, [attempt, workspaceId]);

  async function handleRestore(item: ColumnWorkbenchItem) {
    const csrfToken = window.sessionStorage.getItem("workspace_csrf");
    if (!csrfToken) {
      setState({ status: "failed" });
      return;
    }
    try {
      await restoreColumnDefaults(
        workspaceId,
        item.accountId,
        item.id,
        csrfToken,
      );
      setState({ status: "loading" });
      setAttempt((value) => value + 1);
    } catch {
      setState({ status: "failed" });
    }
  }

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <PageHeader
        description="栏目和活动独立展示账号继承、临时覆盖、有效时间及当前版本。"
        title="栏目与活动"
      />
      {state.status === "loading" ? <Skeleton label="正在加载栏目与活动" /> : null}
      {state.status === "failed" ? (
        <ErrorState
          description="无法安全读取或更新栏目配置，请刷新后重试。"
          title="栏目配置暂不可用"
        />
      ) : null}
      {state.status === "ready" ? (
        <ColumnsCenter
          items={filterColumnsByScope(
            state.items,
            searchParams.get("platform"),
            searchParams.get("account"),
          )}
          onRestoreDefaults={state.context.role === "viewer" ? undefined : handleRestore}
          role={state.context.role}
        />
      ) : null}
    </div>
  );
}
