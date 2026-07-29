import type { ReactNode } from "react";

import { WorkspaceShellLoader } from "@/components/workbench/workspace-shell";


export default async function WorkspaceLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;
  return (
    <WorkspaceShellLoader workspaceId={workspaceId}>
      {children}
    </WorkspaceShellLoader>
  );
}
