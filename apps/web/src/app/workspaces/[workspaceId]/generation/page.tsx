import { CoverEditor } from "@/components/generation/cover-editor/cover-editor";

import { TextEditor } from "./text-editor";


export default async function GenerationPage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;
  return (
    <main className="min-h-screen bg-slate-950 px-5 py-10 text-slate-100 sm:px-8">
      <div className="mx-auto max-w-5xl">
        <TextEditor workspaceId={workspaceId} />
        <div className="mt-10">
          <CoverEditor />
        </div>
      </div>
    </main>
  );
}
