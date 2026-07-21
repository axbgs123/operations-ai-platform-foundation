import { ContentLoader } from "@/components/content/content-loader";


export default async function ContentPage({ params }: { params: Promise<{ contentId: string }> }) {
  const { contentId } = await params;
  return <ContentLoader contentId={contentId} />;
}
