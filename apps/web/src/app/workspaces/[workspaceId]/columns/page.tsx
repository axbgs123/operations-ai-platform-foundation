import { ColumnsCenterPage } from "@/components/account/columns-center";


export default async function ColumnsPage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;
  return <ColumnsCenterPage workspaceId={workspaceId} />;
}
