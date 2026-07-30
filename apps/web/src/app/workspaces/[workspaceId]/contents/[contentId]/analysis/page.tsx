import { redirect } from "next/navigation";

import { sanitizeReturnTo } from "@/components/workbench/scope-query";


export default async function AnalysisPage({
  params,
  searchParams,
}: {
  params: Promise<{ workspaceId: string; contentId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { workspaceId, contentId } = await params;
  const raw = await searchParams;
  const first = (key: string) => {
    const value = raw[key];
    return Array.isArray(value) ? value[0] : value;
  };
  const query = new URLSearchParams({ tab: "analysis" });
  const platform = first("platform");
  if (platform === "douyin" || platform === "xiaohongshu") {
    query.set("platform", platform);
  }
  const account = first("account");
  if (account && /^[A-Za-z0-9-]+$/.test(account)) query.set("account", account);
  const safeReturn = sanitizeReturnTo(workspaceId, first("returnTo"));
  if (safeReturn) query.set("returnTo", safeReturn);
  redirect(
    `/workspaces/${workspaceId}/contents/${contentId}?${query}`,
  );
}
