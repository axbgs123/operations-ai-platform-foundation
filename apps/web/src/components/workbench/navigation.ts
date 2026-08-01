import type { components } from "@operations-ai/shared-schemas";


export type WorkbenchRole =
  components["schemas"]["WorkbenchContextRead"]["role"];

export type WorkbenchNavigationCategoryId =
  | "overview"
  | "operations"
  | "creation"
  | "assets"
  | "management";

export type WorkbenchNavigationItem = {
  label: string;
  href: string;
  icon: string;
  allowedRoles: readonly WorkbenchRole[];
};

export type WorkbenchNavigationCategory = {
  id: WorkbenchNavigationCategoryId;
  label: string;
  navigationLabel: string;
  icon: string;
  defaultHref: string;
  items: readonly WorkbenchNavigationItem[];
};

const ALL_ROLES = ["admin", "editor", "viewer"] as const;
const EDIT_ROLES = ["admin", "editor"] as const;

export const WORKBENCH_NAV_CATEGORIES: readonly WorkbenchNavigationCategory[] = [
  {
    id: "overview",
    label: "总览",
    navigationLabel: "工作台总览",
    icon: "home",
    defaultHref: "",
    items: [
      {
        label: "工作台总览",
        href: "",
        icon: "home",
        allowedRoles: ALL_ROLES,
      },
    ],
  },
  {
    id: "operations",
    label: "运营",
    navigationLabel: "内容运营",
    icon: "operations",
    defaultHref: "/contents",
    items: [
      {
        label: "内容库",
        href: "/contents",
        icon: "contents",
        allowedRoles: ALL_ROLES,
      },
      {
        label: "数据导入",
        href: "/imports",
        icon: "imports",
        allowedRoles: EDIT_ROLES,
      },
      {
        label: "分析中心",
        href: "/analysis",
        icon: "analysis",
        allowedRoles: ALL_ROLES,
      },
      {
        label: "账号仪表盘",
        href: "/accounts",
        icon: "accounts",
        allowedRoles: ALL_ROLES,
      },
      {
        label: "栏目与活动",
        href: "/columns",
        icon: "columns",
        allowedRoles: EDIT_ROLES,
      },
    ],
  },
  {
    id: "creation",
    label: "创作",
    navigationLabel: "AI 创作",
    icon: "creation",
    defaultHref: "/generation",
    items: [
      {
        label: "生成中心",
        href: "/generation",
        icon: "generation",
        allowedRoles: ALL_ROLES,
      },
      {
        label: "发布前检查",
        href: "/preflight",
        icon: "preflight",
        allowedRoles: ALL_ROLES,
      },
    ],
  },
  {
    id: "assets",
    label: "资产",
    navigationLabel: "策略资产",
    icon: "assets",
    defaultHref: "/viral-library",
    items: [
      {
        label: "爆款素材库",
        href: "/viral-library",
        icon: "viral",
        allowedRoles: ALL_ROLES,
      },
      {
        label: "账号风格",
        href: "/styles",
        icon: "styles",
        allowedRoles: ALL_ROLES,
      },
      {
        label: "事实资料",
        href: "/facts",
        icon: "facts",
        allowedRoles: ALL_ROLES,
      },
    ],
  },
  {
    id: "management",
    label: "管理",
    navigationLabel: "工作区管理",
    icon: "management",
    defaultHref: "/data-management/exports",
    items: [
      {
        label: "导出与备份",
        href: "/data-management/exports",
        icon: "exports",
        allowedRoles: EDIT_ROLES,
      },
      {
        label: "后台任务",
        href: "/settings/jobs",
        icon: "jobs",
        allowedRoles: EDIT_ROLES,
      },
      {
        label: "风控知识库",
        href: "/risk-knowledge",
        icon: "risk",
        allowedRoles: ["admin"],
      },
      {
        label: "回收站",
        href: "/data-management/trash",
        icon: "trash",
        allowedRoles: ["admin"],
      },
      {
        label: "工作区设置",
        href: "/settings",
        icon: "settings",
        allowedRoles: ["admin"],
      },
    ],
  },
];

// Kept as a compatibility export while consumers migrate to categories.
export const WORKBENCH_NAV_GROUPS = WORKBENCH_NAV_CATEGORIES;

export const ALL_WORKBENCH_MODULE_LABELS = WORKBENCH_NAV_CATEGORIES.flatMap(
  (category) => category.items.map((item) => item.label),
);

export function visibleCategoryItems(
  category: WorkbenchNavigationCategory,
  role: WorkbenchRole,
): WorkbenchNavigationItem[] {
  return category.items.filter((item) => item.allowedRoles.includes(role));
}

export function visibleNavigationCategories(
  role: WorkbenchRole,
): WorkbenchNavigationCategory[] {
  return WORKBENCH_NAV_CATEGORIES.filter(
    (category) => visibleCategoryItems(category, role).length > 0,
  );
}

export function visibleNavigationItems(
  role: WorkbenchRole,
): WorkbenchNavigationItem[] {
  return visibleNavigationCategories(role).flatMap((category) =>
    visibleCategoryItems(category, role),
  );
}

export function workbenchHref(workspaceId: string, href: string): string {
  return `/workspaces/${workspaceId}${href}`;
}

export function isNavigationItemActive(
  pathname: string,
  workspaceId: string,
  item: WorkbenchNavigationItem,
): boolean {
  const root = `/workspaces/${workspaceId}`;
  const target = `${root}${item.href}`;
  if (item.href === "") return pathname === root || pathname === `${root}/`;
  if (item.href === "/settings/jobs") {
    return pathname === target || pathname.startsWith(`${target}/`);
  }
  if (item.href === "/settings") {
    return (
      (pathname === target || pathname.startsWith(`${target}/`))
      && !pathname.startsWith(`${root}/settings/jobs`)
    );
  }
  return pathname === target || pathname.startsWith(`${target}/`);
}

export function activeNavigationItem(
  pathname: string,
  workspaceId: string,
): WorkbenchNavigationItem | undefined {
  return visibleNavigationItems("admin").find((item) =>
    isNavigationItemActive(pathname, workspaceId, item),
  );
}

export function activeNavigationCategory(
  pathname: string,
  workspaceId: string,
): WorkbenchNavigationCategory | undefined {
  const activeItem = activeNavigationItem(pathname, workspaceId);
  if (!activeItem) return undefined;
  return WORKBENCH_NAV_CATEGORIES.find((category) =>
    category.items.some((item) => item.href === activeItem.href),
  );
}

export function navigationCategory(
  categoryId: WorkbenchNavigationCategoryId,
): WorkbenchNavigationCategory {
  return WORKBENCH_NAV_CATEGORIES.find(
    (category) => category.id === categoryId,
  )!;
}

export function defaultNavigationItem(
  categoryId: WorkbenchNavigationCategoryId,
  role: WorkbenchRole,
): WorkbenchNavigationItem | undefined {
  const category = navigationCategory(categoryId);
  const allowedItems = visibleCategoryItems(category, role);
  return (
    allowedItems.find((item) => item.href === category.defaultHref)
    ?? allowedItems[0]
  );
}
