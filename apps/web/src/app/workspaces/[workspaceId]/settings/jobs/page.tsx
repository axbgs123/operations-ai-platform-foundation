import { JobOperations } from "@/components/operations/job-operations";

export default async function JobsPage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;
  return <JobOperations workspaceId={workspaceId} />;
}
