import { ImportReview } from "@/components/imports/import-review";


export default async function ImportsPage({
  params,
  searchParams,
}: {
  params: Promise<{ workspaceId: string }>;
  searchParams: Promise<{ accountId?: string; platform?: string }>;
}) {
  const { workspaceId } = await params;
  const query = await searchParams;
  if (
    !query.accountId ||
    !["douyin", "xiaohongshu"].includes(query.platform ?? "")
  ) {
    return <main className="p-10">缺少账号或平台参数</main>;
  }
  return (
    <main className="min-h-screen bg-slate-950 px-5 py-10 text-slate-100 sm:px-8">
      <div className="mx-auto max-w-6xl">
        <ImportReview
          accountId={query.accountId}
          platform={query.platform as "douyin" | "xiaohongshu"}
          workspaceId={workspaceId}
        />
      </div>
    </main>
  );
}
