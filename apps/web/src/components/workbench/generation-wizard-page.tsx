"use client";

import { useRouter, useSearchParams } from "next/navigation";
import {
  useEffect,
  useMemo,
  useState,
  type ReactElement,
} from "react";

import { FactSourceCenter } from "@/components/facts/fact-source-center";
import {
  GenerationWizard,
  normalizeGenerationStep,
  type GenerationWizardFixture,
  type GenerationWizardState,
} from "@/components/workbench/generation-wizard";
import { useWorkbenchShellContext } from "@/components/workbench/workspace-shell";
import { ErrorState, Skeleton } from "@/components/workbench/ui";
import { getFactContext, listFactSources } from "@/lib/fact-api";
import {
  getModelUsageSummary,
  listModelConfigs,
  listModelUsagePolicies,
} from "@/lib/model-api";
import { listStyleProfiles, listStyleScopes } from "@/lib/style-api";
import { listViralLibrary } from "@/lib/viral-api";


type LoadState =
  | { status: "loading" }
  | {
      status: "ready";
      fixture: GenerationWizardFixture;
      accountScope: string | null;
    }
  | { status: "failed"; message: string };

export function GenerationWizardPage({
  workspaceId,
}: {
  workspaceId: string;
}): ReactElement {
  const context = useWorkbenchShellContext();
  const searchParams = useSearchParams();
  const router = useRouter();
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const scopedPlatform =
    searchParams.get("platform") === "douyin"
    || searchParams.get("platform") === "xiaohongshu"
      ? searchParams.get("platform") as "douyin" | "xiaohongshu"
      : null;
  const requestedAccountId = searchParams.get("account");
  const selectedAccountId = context?.accounts.find(
    (account) =>
      account.account_id === requestedAccountId
      && (!scopedPlatform || account.platform === scopedPlatform),
  )?.account_id ?? null;

  useEffect(() => {
    if (!context) return;
    let active = true;
    Promise.all([
      listModelConfigs(workspaceId),
      context.role === "admin"
        ? listModelUsagePolicies(workspaceId)
        : Promise.resolve([]),
      context.role === "admin"
        ? getModelUsageSummary(workspaceId)
        : Promise.resolve(null),
      listFactSources(workspaceId),
      getFactContext(workspaceId),
    ])
      .then(([
        models,
        modelUsagePolicies,
        modelUsageSummary,
        factSources,
        factContext,
      ]) => {
        if (!active) return;
        setState({
          status: "ready",
          accountScope: null,
          fixture: {
            accounts: context.accounts,
            columns: [],
            models,
            modelUsagePolicies,
            modelUsageSummary,
            factSources,
            factContext,
            styles: [],
            viralItems: [],
            riskScan: null,
          },
        });
      })
      .catch((caught: unknown) => {
        if (active) {
          setState({
            status: "failed",
            message: caught instanceof Error
              ? caught.message
              : "生成中心依赖加载失败",
          });
        }
      });
    return () => {
      active = false;
    };
  }, [context, workspaceId]);

  useEffect(() => {
    if (state.status !== "ready") return;
    if (!selectedAccountId) return;
    let active = true;
    Promise.all([
      listStyleScopes(workspaceId, selectedAccountId),
      listStyleProfiles(workspaceId, selectedAccountId),
      listViralLibrary(workspaceId, selectedAccountId),
    ])
      .then(([columns, styles, viralItems]) => {
        if (!active) return;
        setState((current) => current.status === "ready"
          ? {
              status: "ready",
              accountScope: selectedAccountId,
              fixture: {
                ...current.fixture,
                columns,
                styles,
                viralItems: viralItems.filter((item) => item.generation_eligible),
              },
            }
          : current);
      })
      .catch((caught: unknown) => {
        if (active) {
          setState({
            status: "failed",
            message: caught instanceof Error
              ? caught.message
              : "账号风格与参考加载失败",
          });
        }
      });
    return () => {
      active = false;
    };
  }, [selectedAccountId, state.status, workspaceId]);

  const initialStep = normalizeGenerationStep(searchParams.get("step"));
  const currentQuery = useMemo(
    () => new URLSearchParams(searchParams.toString()),
    [searchParams],
  );

  if (!context || state.status === "loading") {
    return <Skeleton label="正在加载生成中心" />;
  }
  if (state.status === "failed") {
    return <ErrorState description={state.message} title="生成中心加载失败" />;
  }
  if (selectedAccountId && state.accountScope !== selectedAccountId) {
    return <Skeleton label="正在加载账号生成配置" />;
  }
  const scopedFixture = selectedAccountId
    ? state.fixture
    : {
        ...state.fixture,
        columns: [],
        styles: [],
        viralItems: [],
      };

  function syncUrl(next: GenerationWizardState) {
    const query = new URLSearchParams(currentQuery);
    query.set("step", next.step);
    const account = context?.accounts.find(
      (candidate) => candidate.account_id === next.accountId,
    );
    if (account) {
      query.set("platform", account.platform);
      query.set("account", account.account_id);
    } else {
      query.delete("account");
    }
    router.replace(`/workspaces/${workspaceId}/generation?${query}`);
  }

  return (
    <GenerationWizard
      fixture={scopedFixture}
      initialAccountId={selectedAccountId}
      initialPlatform={scopedPlatform}
      initialStep={initialStep}
      memberId={context.member_id}
      onPlatformChange={(platform) => {
        const query = new URLSearchParams(currentQuery);
        if (platform) query.set("platform", platform);
        else query.delete("platform");
        query.delete("account");
        router.replace(`/workspaces/${workspaceId}/generation?${query}`);
      }}
      onStateChange={(next) => {
        syncUrl(next);
      }}
      onStepChange={() => undefined}
      role={context.role}
      sourceManager={
        <details className="rounded-lg border p-4">
          <summary className="cursor-pointer font-semibold">
            添加或确认事实资料
          </summary>
          <div className="mt-4">
            <FactSourceCenter role={context.role} workspaceId={workspaceId} />
          </div>
        </details>
      }
      workspaceId={workspaceId}
    />
  );
}
