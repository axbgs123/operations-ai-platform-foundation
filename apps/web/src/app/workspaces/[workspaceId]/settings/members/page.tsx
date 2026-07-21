import { MemberSettings } from "@/components/workspace/member-settings";


export default async function MembersPage({
  params,
}: PageProps<"/workspaces/[workspaceId]/settings/members">) {
  const { workspaceId } = await params;

  return (
    <main className="min-h-screen bg-slate-950 px-6 py-12 text-slate-100">
      <div className="mx-auto max-w-4xl">
        <MemberSettings workspaceId={workspaceId} />
      </div>
    </main>
  );
}
