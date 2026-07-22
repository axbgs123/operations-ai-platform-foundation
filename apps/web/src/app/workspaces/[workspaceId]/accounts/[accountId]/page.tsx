import { AccountDashboard } from "@/components/charts/account-dashboard";


export default async function AccountDashboardPage({
  params,
  searchParams,
}: {
  params: Promise<{ workspaceId: string; accountId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { workspaceId, accountId } = await params;
  const query = await searchParams;
  const contentType = query.content_type === "video" ? "video" : "image_text";
  const maturityBucket = ["1h", "24h", "72h", "7d"].includes(
    String(query.maturity_bucket),
  ) ? query.maturity_bucket as "1h" | "24h" | "72h" | "7d" : "24h";
  return (
    <main className="min-h-screen bg-slate-950 px-4 py-8 text-slate-100 sm:px-6 sm:py-10">
      <div className="mx-auto max-w-7xl">
        <AccountDashboard
          accountId={accountId}
          initialContentType={contentType}
          initialMaturityBucket={maturityBucket}
          workspaceId={workspaceId}
        />
      </div>
    </main>
  );
}
