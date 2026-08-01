import type { ReactElement } from "react";

import {
  activeNavigationCategory,
  navigationCategory,
  type WorkbenchRole,
} from "./navigation";
import { PrimaryNav } from "./primary-nav";
import { SecondaryNav } from "./secondary-nav";


export function SidebarNav({
  workspaceId,
  memberId = "navigation-member",
  role,
  pathname,
  collapsed,
  onNavigate,
  onToggleSecondary = () => undefined,
}: {
  workspaceId: string;
  memberId?: string;
  role: WorkbenchRole;
  pathname: string;
  collapsed: boolean;
  onNavigate: () => void;
  onToggleSecondary?: () => void;
}): ReactElement {
  const activeCategory = (
    activeNavigationCategory(pathname, workspaceId)
    ?? navigationCategory("overview")
  );
  return (
    <div className="flex h-full">
      <PrimaryNav
        memberId={memberId}
        onNavigate={onNavigate}
        onToggleSecondary={onToggleSecondary}
        pathname={pathname}
        role={role}
        secondaryCollapsed={collapsed}
        workspaceId={workspaceId}
      />
      {!collapsed ? (
        <SecondaryNav
          category={activeCategory}
          onCollapse={onToggleSecondary}
          onNavigate={onNavigate}
          pathname={pathname}
          role={role}
          workspaceId={workspaceId}
        />
      ) : null}
    </div>
  );
}
