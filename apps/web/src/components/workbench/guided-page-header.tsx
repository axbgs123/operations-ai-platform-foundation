"use client";

import type { ReactNode } from "react";

import { OPERATOR_COPY_CATALOG, type OperatorPageId } from "./operator-copy-catalog";
import { PageGuide } from "./page-guide";
import { PageHeader, type DisplayCopy } from "./ui";

export function GuidedPageHeader({
  pageId,
  title,
  context,
  primaryAction,
  secondaryActions,
}: {
  pageId: OperatorPageId;
  title?: string;
  context?: DisplayCopy;
  primaryAction?: ReactNode;
  secondaryActions?: ReactNode;
}) {
  const page = OPERATOR_COPY_CATALOG[pageId];
  return (
    <div>
      <PageHeader
        description={context}
        primaryAction={primaryAction}
        secondaryActions={secondaryActions}
        title={title ?? page.title}
      />
      <PageGuide pageId={pageId} />
    </div>
  );
}
