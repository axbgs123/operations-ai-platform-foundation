import { ViralLibraryPage as ViralLibraryContent } from "@/components/viral/viral-library";


export default async function ViralLibraryPage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;
  return <ViralLibraryContent workspaceId={workspaceId} />;
}
