import { ContentDetailPage } from "@/components/content/content-detail-tabs";


export default async function ContentPage({
  params,
}: {
  params: Promise<{ workspaceId: string; contentId: string }>;
}) {
  const { workspaceId, contentId } = await params;
  return <ContentDetailPage contentId={contentId} workspaceId={workspaceId} />;
}
