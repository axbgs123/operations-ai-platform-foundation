import { AnalysisPanel } from "./analysis-panel";


export default async function AnalysisPage({
  params,
}: {
  params: Promise<{ workspaceId: string; contentId: string }>;
}) {
  const { workspaceId, contentId } = await params;
  return (
    <main className="min-h-screen bg-slate-950 px-5 py-10 text-slate-100 sm:px-8">
      <div className="mx-auto max-w-5xl">
        <AnalysisPanel contentId={contentId} workspaceId={workspaceId} />
      </div>
    </main>
  );
}
