import { ViralLibrary } from "@/components/viral/viral-library";


export default async function ViralLibraryPage({
  params,
  searchParams,
}: {
  params: Promise<{ workspaceId: string }>;
  searchParams: Promise<{ account_id?: string; accountId?: string }>;
}) {
  const { workspaceId } = await params;
  const query = await searchParams;
  const accountId = query.account_id ?? query.accountId;
  if (!accountId) {
    return <main className="p-10">缺少账号参数</main>;
  }
  return (
    <main className="min-h-screen bg-slate-950 px-5 py-10 text-slate-100 sm:px-8">
      <div className="mx-auto max-w-6xl">
        <ViralLibrary accountId={accountId} workspaceId={workspaceId} />
      </div>
    </main>
  );
}
