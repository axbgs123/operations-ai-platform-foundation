import { AccountSettings } from "@/components/account/account-settings";


export default async function AccountSettingsPage({
  params,
}: {
  params: Promise<{ workspaceId: string; accountId: string }>;
}) {
  const { workspaceId, accountId } = await params;
  return (
    <main className="min-h-screen bg-slate-950 px-6 py-10 text-slate-100">
      <div className="mx-auto max-w-4xl">
        <AccountSettings accountId={accountId} workspaceId={workspaceId} />
      </div>
    </main>
  );
}
