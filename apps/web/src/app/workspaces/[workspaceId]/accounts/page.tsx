import { AccountListPage } from "@/components/account/account-list";


export default async function AccountsPage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;
  return <AccountListPage workspaceId={workspaceId} />;
}
