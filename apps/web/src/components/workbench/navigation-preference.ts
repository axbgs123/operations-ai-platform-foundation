import {
  navigationCategory,
  type WorkbenchNavigationCategoryId,
  type WorkbenchNavigationItem,
  type WorkbenchRole,
  visibleCategoryItems,
} from "./navigation";


function recentNavigationKey(
  memberId: string,
  categoryId: WorkbenchNavigationCategoryId,
): string {
  return `operations-ai:navigation:${memberId}:${categoryId}`;
}

export function readRecentNavigationPath(
  storage: Storage,
  memberId: string,
  categoryId: WorkbenchNavigationCategoryId,
  role: WorkbenchRole,
): string | undefined {
  const stored = storage.getItem(recentNavigationKey(memberId, categoryId));
  if (stored === null) return undefined;
  const allowedItems = visibleCategoryItems(
    navigationCategory(categoryId),
    role,
  );
  return allowedItems.some((item) => item.href === stored)
    ? stored
    : undefined;
}

export function writeRecentNavigationPath(
  storage: Storage,
  memberId: string,
  categoryId: WorkbenchNavigationCategoryId,
  item: WorkbenchNavigationItem,
): void {
  const category = navigationCategory(categoryId);
  if (!category.items.some((candidate) => candidate.href === item.href)) {
    return;
  }
  storage.setItem(recentNavigationKey(memberId, categoryId), item.href);
}
