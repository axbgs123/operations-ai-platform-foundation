import { TrashCenter } from "@/components/exports/trash-center";

export default async function TrashPage({
  params,
}: PageProps<"/workspaces/[workspaceId]/data-management/trash">) {
  const { workspaceId } = await params;
  return (
    <TrashCenter
      evaluatedAt={new Date().toISOString()}
      workspaceId={workspaceId}
    />
  );
}
