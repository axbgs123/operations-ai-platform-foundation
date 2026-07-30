import { ContentLibraryPage } from "@/components/content/content-list";


export default async function ContentsPage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;
  return <ContentLibraryPage workspaceId={workspaceId} />;
}
