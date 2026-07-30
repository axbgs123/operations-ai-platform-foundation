import { redirect } from "next/navigation";

import { sanitizeReturnTo } from "@/components/workbench/scope-query";


export default async function AccountSettingsPage({
  params,
  searchParams,
}: {
  params: Promise<{ workspaceId: string; accountId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { workspaceId, accountId } = await params;
  const raw = await searchParams;
  const first = (key: string) => {
    const value = raw[key];
    return Array.isArray(value) ? value[0] : value;
  };
  const query = new URLSearchParams();
  const platform = first("platform");
  if (platform === "douyin" || platform === "xiaohongshu") {
    query.set("platform", platform);
  }
  if (first("account") === accountId) {
    query.set("account", accountId);
  }
  const safeReturn = sanitizeReturnTo(workspaceId, first("returnTo"));
  if (safeReturn) query.set("returnTo", safeReturn);
  const suffix = query.size ? `?${query}` : "";
  redirect(
    `/workspaces/${workspaceId}/accounts/${accountId}${suffix}`,
  );
}
