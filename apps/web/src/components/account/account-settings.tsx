"use client";

import { useEffect, useState } from "react";

import { AccountConfigEditor } from "@/components/account/account-config-editor";
import { EffectiveAccountConfiguration, loadEffectiveAccountConfiguration } from "@/lib/account-api";


export function AccountSettings({ workspaceId, accountId }: { workspaceId: string; accountId: string }) {
  const [configuration, setConfiguration] = useState<EffectiveAccountConfiguration>();
  const [error, setError] = useState("");

  useEffect(() => {
    loadEffectiveAccountConfiguration(workspaceId, accountId)
      .then(setConfiguration)
      .catch((caught) => setError(caught instanceof Error ? caught.message : "加载失败"));
  }, [workspaceId, accountId]);

  if (error) return <p className="text-rose-400">{error}</p>;
  if (!configuration) return <p className="text-slate-400">正在加载账号配置…</p>;
  return (
    <AccountConfigEditor
      accountId={accountId}
      initialBenchmarkSampleSize={configuration.benchmark_profile.sample_size}
      initialObjectives={configuration.objective_profile.objectives}
      initialWeights={configuration.objective_profile.metric_weights}
      workspaceId={workspaceId}
    />
  );
}
