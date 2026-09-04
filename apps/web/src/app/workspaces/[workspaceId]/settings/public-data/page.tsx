import { PublicDataProviderSettings } from "@/components/public-data/provider-settings";
import { SettingsNav } from "@/components/workspace/settings-nav";


export default async function PublicDataSettingsPage({
  params,
}: PageProps<"/workspaces/[workspaceId]/settings/public-data">) {
  const { workspaceId } = await params;
  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <SettingsNav workspaceId={workspaceId} />
      <PublicDataProviderSettings workspaceId={workspaceId} />
    </div>
  );
}
