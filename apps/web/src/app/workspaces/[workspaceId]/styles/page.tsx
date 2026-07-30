import { StyleAccountSelectorPage } from "@/components/styles/style-account-selector";

export default async function StylesPage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;
  return <StyleAccountSelectorPage workspaceId={workspaceId} />;
}
