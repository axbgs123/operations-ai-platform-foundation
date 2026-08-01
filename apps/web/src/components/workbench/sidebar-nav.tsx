import type { ReactElement } from "react";

import {
  activeNavigationCategory,
  navigationCategory,
  visibleCategoryItems,
  type WorkbenchRole,
} from "./navigation";
import { PrimaryNav } from "./primary-nav";
import { SecondaryNav } from "./secondary-nav";
import type { WorkbenchScope } from "./scope-query";


export function SidebarNav({
  workspaceId,
  memberId = "navigation-member",
  role,
  pathname,
  scope = {},
  collapsed,
  onNavigate,
  onToggleSecondary = () => undefined,
}: {
  workspaceId: string;
  memberId?: string;
  role: WorkbenchRole;
  pathname: string;
  scope?: WorkbenchScope;
  collapsed: boolean;
  onNavigate: () => void;
  onToggleSecondary?: () => void;
}): ReactElement {
  const routeCategory = activeNavigationCategory(pathname, workspaceId);
  const activeCategory = (
    routeCategory && visibleCategoryItems(routeCategory, role).length > 0
      ? routeCategory
      : navigationCategory("overview")
  );
  return (
    <div className="flex h-full">
      <PrimaryNav
        memberId={memberId}
        onNavigate={onNavigate}
        onToggleSecondary={onToggleSecondary}
        pathname={pathname}
        role={role}
        scope={scope}
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
          scope={scope}
          workspaceId={workspaceId}
        />
      ) : null}
    </div>
  );
}
