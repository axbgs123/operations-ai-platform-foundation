import { ModelConfigForm } from "@/components/models/model-config-form";


export default async function ModelsPage({
  params,
}: PageProps<"/workspaces/[workspaceId]/settings/models">) {
  const { workspaceId } = await params;

  return (
    <main className="min-h-screen bg-slate-950 px-4 py-10 text-slate-100 sm:px-6">
      <div className="mx-auto max-w-4xl">
        <ModelConfigForm workspaceId={workspaceId} />
      </div>
    </main>
  );
}
