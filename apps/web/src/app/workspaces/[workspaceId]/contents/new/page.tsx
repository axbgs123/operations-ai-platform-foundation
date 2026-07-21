import { NewContentForm } from "@/components/content/new-content-form";


export default async function NewContentPage({
  params,
  searchParams,
}: {
  params: Promise<{ workspaceId: string }>;
  searchParams: Promise<{ accountId?: string; platform?: string }>;
}) {
  const { workspaceId } = await params;
  const query = await searchParams;
  if (!query.accountId || !["douyin", "xiaohongshu"].includes(query.platform ?? "")) {
    return <main className="p-10">缺少账号或平台参数</main>;
  }
  return <main className="min-h-screen bg-slate-950 px-6 py-10 text-slate-100"><NewContentForm accountId={query.accountId} platform={query.platform as "douyin" | "xiaohongshu"} workspaceId={workspaceId} /></main>;
}
