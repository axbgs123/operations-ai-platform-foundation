import { RiskKnowledgeCenter } from "@/components/risk/risk-knowledge-center";

export default async function RiskKnowledgePage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;
  return <RiskKnowledgeCenter role="admin" workspaceId={workspaceId} />;
}
