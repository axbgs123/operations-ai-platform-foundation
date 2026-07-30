import { ModelConfigForm } from "@/components/models/model-config-form";
import { SettingsNav } from "@/components/workspace/settings-nav";


export default async function ModelsPage({
  params,
}: PageProps<"/workspaces/[workspaceId]/settings/models">) {
  const { workspaceId } = await params;

  return (
    <div className="mx-auto max-w-5xl space-y-6">
        <SettingsNav workspaceId={workspaceId} />
        <ModelConfigForm workspaceId={workspaceId} />
    </div>
  );
}
