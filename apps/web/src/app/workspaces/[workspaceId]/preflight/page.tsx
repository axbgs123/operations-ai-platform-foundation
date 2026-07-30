import { PreflightQueuePage } from "@/components/risk/preflight-queue";


export default async function PreflightPage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;
  return <PreflightQueuePage workspaceId={workspaceId} />;
}
