import { AgentWorkspacePage } from "@/components/agent/agent-workspace-page";


export default async function OperationsAgentPage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;
  return <AgentWorkspacePage workspaceId={workspaceId} />;
}
