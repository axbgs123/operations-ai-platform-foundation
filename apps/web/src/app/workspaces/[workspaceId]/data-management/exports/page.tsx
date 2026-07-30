import { ExportBackupCenter } from "@/components/exports/export-backup-center";

export default async function ExportsPage({
  params,
}: PageProps<"/workspaces/[workspaceId]/data-management/exports">) {
  const { workspaceId } = await params;
  return (
    <ExportBackupCenter
      evaluatedAt={new Date().toISOString()}
      workspaceId={workspaceId}
    />
  );
}
