import { HotspotReview } from "@/components/hotspots/hotspot-review";

export default async function HotspotsPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = await params;
  return <HotspotReview workspaceId={workspaceId} />;
}
