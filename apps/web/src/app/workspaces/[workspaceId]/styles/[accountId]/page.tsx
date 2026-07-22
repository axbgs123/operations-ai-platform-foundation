import { StyleProfileCenter } from "@/components/styles/style-profile-center";


export default async function AccountStylePage({
  params,
  searchParams,
}: {
  params: Promise<{ workspaceId: string; accountId: string }>;
  searchParams: Promise<{ columnCampaignId?: string }>;
}) {
  const { workspaceId, accountId } = await params;
  const { columnCampaignId } = await searchParams;
  return (
    <main className="min-h-screen bg-slate-950 px-6 py-10 text-slate-100">
      <div className="mx-auto max-w-6xl">
        <StyleProfileCenter
          accountId={accountId}
          columnCampaignId={columnCampaignId}
          workspaceId={workspaceId}
        />
      </div>
    </main>
  );
}
