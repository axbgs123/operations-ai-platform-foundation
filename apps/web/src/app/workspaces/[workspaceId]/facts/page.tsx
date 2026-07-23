import { FactSourceCenter } from "@/components/facts/fact-source-center";


export default async function FactsPage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;
  return (
    <main className="min-h-screen bg-slate-950 px-6 py-10 text-slate-100">
      <div className="mx-auto max-w-6xl">
        <FactSourceCenter workspaceId={workspaceId} />
      </div>
    </main>
  );
}
