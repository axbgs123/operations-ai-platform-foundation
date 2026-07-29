import type { components } from "@operations-ai/shared-schemas";


export type WorkbenchRole =
  components["schemas"]["WorkbenchContextRead"]["role"];

export type WorkbenchNavigationItem = {
  label: string;
  href: string;
  icon: string;
  allowedRoles: readonly WorkbenchRole[];
};

export type WorkbenchNavigationGroup = {
  label: string;
  items: readonly WorkbenchNavigationItem[];
};

const ALL_ROLES = ["admin", "editor", "viewer"] as const;
const EDIT_ROLES = ["admin", "editor"] as const;

export const WORKBENCH_NAV_GROUPS: readonly WorkbenchNavigationGroup[] = [
  {
    label: "工作台",
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
    label: "内容运营",
    items: [
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
    ],
  },
  {
    label: "策略资产",
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
    label: "AI 创作",
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
    label: "治理与数据",
    items: [
      {
        label: "风控知识库",
        href: "/risk-knowledge",
        icon: "risk",
        allowedRoles: ["admin"],
      },
      {
        label: "导出与备份",
        href: "/data-management/exports",
        icon: "exports",
        allowedRoles: EDIT_ROLES,
      },
      {
        label: "回收站",
        href: "/data-management/trash",
        icon: "trash",
        allowedRoles: ["admin"],
      },
    ],
  },
  {
    label: "工作区管理",
    items: [
      {
        label: "后台任务",
        href: "/settings/jobs",
        icon: "jobs",
        allowedRoles: EDIT_ROLES,
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

export const ALL_WORKBENCH_MODULE_LABELS = WORKBENCH_NAV_GROUPS.flatMap(
  (group) => group.items.map((item) => item.label),
);

export function visibleNavigationItems(
  role: WorkbenchRole,
): WorkbenchNavigationItem[] {
  return WORKBENCH_NAV_GROUPS.flatMap((group) =>
    group.items.filter((item) => item.allowedRoles.includes(role)),
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
