import { FactSourceCenter } from "@/components/facts/fact-source-center";


export default async function FactsPage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;
  return <FactSourceCenter workspaceId={workspaceId} />;
}
