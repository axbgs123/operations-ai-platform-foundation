import { AnalysisQueuePage } from "@/components/analysis/analysis-queue";


export default async function AnalysisPage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;
  return <AnalysisQueuePage workspaceId={workspaceId} />;
}
