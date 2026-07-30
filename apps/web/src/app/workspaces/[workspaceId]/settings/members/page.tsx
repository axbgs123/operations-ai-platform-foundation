import { MemberSettings } from "@/components/workspace/member-settings";
import { SettingsNav } from "@/components/workspace/settings-nav";


export default async function MembersPage({
  params,
}: PageProps<"/workspaces/[workspaceId]/settings/members">) {
  const { workspaceId } = await params;

  return (
    <div className="mx-auto max-w-5xl space-y-6">
        <SettingsNav workspaceId={workspaceId} />
        <MemberSettings workspaceId={workspaceId} />
    </div>
  );
}
