import { DrillDownContentList } from "@/components/charts/drill-down-content-list";


export default async function ContentsPage({
  params,
  searchParams,
}: {
  params: Promise<{ workspaceId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { workspaceId } = await params;
  const raw = await searchParams;
  const first = (key: string) => {
    const value = raw[key];
    return Array.isArray(value) ? value[0] : value;
  };
  const all = (key: string) => {
    const value = raw[key];
    if (value === undefined) return [];
    return Array.isArray(value) ? value : [value];
  };
  const platform = first("platform");
  const contentType = first("content_type");
  const maturityBucket = first("maturity_bucket");
  const attention = first("attention");
  return (
    <main className="min-h-screen bg-slate-950 px-4 py-8 text-slate-100 sm:px-6 sm:py-10">
      <div className="mx-auto max-w-7xl">
        <DrillDownContentList
          filters={{
            account_id: first("account_id"),
            platform: platform === "douyin" || platform === "xiaohongshu"
              ? platform : undefined,
            content_type: contentType === "video" || contentType === "image_text"
              ? contentType : undefined,
            maturity_bucket: ["1h", "24h", "72h", "7d"].includes(
              String(maturityBucket),
            ) ? maturityBucket as "1h" | "24h" | "72h" | "7d" : undefined,
            metric_key: first("metric_key"),
            required_metric_keys: all("required_metric_keys"),
            attention: attention === "candidate" || attention === "anomaly"
              ? attention : undefined,
          }}
          workspaceId={workspaceId}
        />
      </div>
    </main>
  );
}
