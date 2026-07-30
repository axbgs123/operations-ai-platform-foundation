import { ImportCenterPage } from "@/components/imports/import-center";


export default async function ImportsPage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;
  return <ImportCenterPage workspaceId={workspaceId} />;
}
