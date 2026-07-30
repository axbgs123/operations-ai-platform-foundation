import { WorkspaceSettings } from "@/components/workspace/workspace-settings";

export default async function SettingsPage({
  params,
}: PageProps<"/workspaces/[workspaceId]/settings">) {
  const { workspaceId } = await params;
  return <WorkspaceSettings workspaceId={workspaceId} />;
}
