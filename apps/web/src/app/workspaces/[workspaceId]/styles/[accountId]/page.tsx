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
      <div className="mx-auto max-w-6xl">
        <StyleProfileCenter
          accountId={accountId}
          columnCampaignId={columnCampaignId}
          workspaceId={workspaceId}
        />
      </div>
  );
}
