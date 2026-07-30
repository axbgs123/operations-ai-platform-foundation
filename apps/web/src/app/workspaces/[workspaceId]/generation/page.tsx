import { GenerationWizardPage } from "@/components/workbench/generation-wizard-page";


export default async function GenerationPage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;
  return <GenerationWizardPage workspaceId={workspaceId} />;
}
