import { WorkbenchOverviewPage } from "@/components/workbench/workbench-overview";


export default async function WorkbenchPage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;
  return <WorkbenchOverviewPage workspaceId={workspaceId} />;
}
