# Two-Level Workbench Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the always-expanded 16-item workbench sidebar with a five-category primary rail and one contextual secondary navigation while preserving routes, roles, scope, security, and mobile accessibility.

**Architecture:** Extend the existing static navigation model with stable category IDs, defaults, and role-filtered helpers. Compose desktop navigation from separate primary and secondary components, persist only the secondary-column display preference and a validated last-visited child per member/category, and convert the current mobile drawer into a two-step category/child flow. No API, database, permission, or business-page changes are required.

**Tech Stack:** Next.js 16 App Router, React 19, TypeScript 5, Tailwind CSS 4, Vitest/Testing Library, Playwright.

## Global Constraints

- Implement against `docs/superpowers/specs/2026-08-01-two-level-workbench-navigation-design.md`.
- Preserve all 16 canonical routes and the Admin 16 / Editor 13 / Viewer 9 visibility matrix.
- Preserve the existing WorkspaceShell context API, platform/account scope, safe `returnTo`, and server-side authorization.
- Use exactly five primary categories: `overview`, `operations`, `creation`, `assets`, `management`.
- Desktop primary rail is 80px; secondary navigation is 184px; expanded total is 264px.
- Collapsed desktop state hides only the secondary navigation and leaves the 80px primary rail visible.
- Mobile below 768px uses one modal drawer with category and child steps, never two side-by-side columns.
- Do not add a category landing page, third-level navigation, API, migration, dependency, online font, or business feature.
- Persist only `expanded|collapsed` and validated canonical child paths, namespaced by member ID.
- Do not store query bodies, invite codes, sessions, tokens, keys, prompts, private content, external URLs, or unvalidated `returnTo`.
- Follow RED → GREEN TDD and commit each task independently.

## File Structure

- `apps/web/src/components/workbench/navigation.ts`: canonical category and child navigation model plus active/default helpers.
- `apps/web/src/components/workbench/navigation-preference.ts`: member-scoped, validated recent-child storage.
- `apps/web/src/components/workbench/primary-nav.tsx`: 80px role-aware category rail.
- `apps/web/src/components/workbench/secondary-nav.tsx`: current-category child navigation.
- `apps/web/src/components/workbench/sidebar-nav.tsx`: desktop composition boundary.
- `apps/web/src/components/workbench/mobile-drawer.tsx`: two-step mobile navigation.
- `apps/web/src/components/workbench/workspace-shell.tsx`: desktop widths, preference wiring, and recent-route updates.
- `apps/web/src/components/workbench/breadcrumbs.tsx`: `workspace / category / page` hierarchy.
- `apps/web/src/components/workbench/workspace-shell.test.tsx`: component, role, storage, width, breadcrumb, and mobile tests.
- `tests/e2e/workbench-navigation.spec.ts`: visible navigation and role route acceptance.
- `tests/e2e/workbench-mobile.spec.ts`: 390px two-step drawer.
- `tests/e2e/workbench-visual.spec.ts`: expanded, collapsed, and mobile visual baselines.

---

### Task 1: Canonical Category Model and Safe Recent-Child Preference

**Files:**
- Modify: `apps/web/src/components/workbench/navigation.ts`
- Create: `apps/web/src/components/workbench/navigation-preference.ts`
- Modify: `apps/web/src/components/workbench/workspace-shell.test.tsx`

**Interfaces:**
- Produces `WorkbenchNavigationCategoryId = "overview" | "operations" | "creation" | "assets" | "management"`.
- Produces `visibleNavigationCategories(role): WorkbenchNavigationCategory[]`.
- Produces `activeNavigationCategory(pathname, workspaceId): WorkbenchNavigationCategory | undefined`.
- Produces `defaultNavigationItem(categoryId, role): WorkbenchNavigationItem | undefined`.
- Produces `readRecentNavigationPath(storage, memberId, categoryId, role): string | undefined`.
- Produces `writeRecentNavigationPath(storage, memberId, categoryId, item): void`.

- [ ] **Step 1: Write failing category, role, default, and storage tests**

```tsx
test("maps all sixteen modules into five stable categories", () => {
  expect(WORKBENCH_NAV_CATEGORIES.map((category) => category.id)).toEqual([
    "overview",
    "operations",
    "creation",
    "assets",
    "management",
  ]);
  expect(ALL_WORKBENCH_MODULE_LABELS).toHaveLength(16);
  expect(new Set(ALL_WORKBENCH_MODULE_LABELS)).toHaveLength(16);
});

test("hides empty categories for the current role", () => {
  expect(visibleNavigationCategories("viewer").map(({ id }) => id)).toEqual([
    "overview",
    "operations",
    "creation",
    "assets",
  ]);
  expect(visibleNavigationCategories("editor")).toHaveLength(5);
  expect(visibleNavigationCategories("admin")).toHaveLength(5);
});

test("rejects a recent child outside its category or role", () => {
  localStorage.setItem(
    "operations-ai:navigation:member-viewer:management",
    "/settings",
  );
  expect(
    readRecentNavigationPath(
      localStorage,
      "member-viewer",
      "management",
      "viewer",
    ),
  ).toBeUndefined();
});
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run:

```bash
pnpm --filter web test:run -- src/components/workbench/workspace-shell.test.tsx
```

Expected: failure because category IDs and recent-navigation functions do not exist.

- [ ] **Step 3: Implement the exact category mapping**

Use this shape:

```ts
export type WorkbenchNavigationCategoryId =
  | "overview"
  | "operations"
  | "creation"
  | "assets"
  | "management";

export type WorkbenchNavigationCategory = {
  id: WorkbenchNavigationCategoryId;
  label: string;
  icon: string;
  defaultHref: string;
  items: readonly WorkbenchNavigationItem[];
};
```

Map and order items exactly:

```ts
overview: ["工作台总览"]
operations: ["内容库", "数据导入", "分析中心", "账号仪表盘", "栏目与活动"]
creation: ["生成中心", "发布前检查"]
assets: ["爆款素材库", "账号风格", "事实资料"]
management: ["导出与备份", "后台任务", "风控知识库", "回收站", "工作区设置"]
```

Defaults are `""`, `"/contents"`, `"/generation"`, `"/viral-library"`, and `"/data-management/exports"`.

- [ ] **Step 4: Implement validated recent-child storage**

Use key:

```ts
`operations-ai:navigation:${memberId}:${categoryId}`
```

Store only `item.href`. On read, find the category, filter items by role, and return the stored value only when it exactly matches an allowed item href. Reject full URLs, query strings, fragments, paths from another category, and invalid role/category combinations.

- [ ] **Step 5: Run focused tests and static checks**

```bash
pnpm --filter web test:run -- src/components/workbench/workspace-shell.test.tsx
pnpm --filter web lint
pnpm --filter web typecheck
git diff --check
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/components/workbench/navigation.ts apps/web/src/components/workbench/navigation-preference.ts apps/web/src/components/workbench/workspace-shell.test.tsx
git commit -m "refactor: model workbench navigation categories"
```

---

### Task 2: Desktop Primary Rail, Secondary Navigation, and Breadcrumb Hierarchy

**Files:**
- Create: `apps/web/src/components/workbench/primary-nav.tsx`
- Create: `apps/web/src/components/workbench/secondary-nav.tsx`
- Modify: `apps/web/src/components/workbench/sidebar-nav.tsx`
- Modify: `apps/web/src/components/workbench/workspace-shell.tsx`
- Modify: `apps/web/src/components/workbench/breadcrumbs.tsx`
- Modify: `apps/web/src/components/workbench/workspace-topbar.tsx`
- Modify: `apps/web/src/components/workbench/workspace-shell.test.tsx`

**Interfaces:**
- Consumes Task 1 category and preference helpers.
- `PrimaryNav` receives workspace ID, role, pathname, member ID, and navigation callback.
- `SecondaryNav` receives the active category, role, pathname, workspace ID, collapsed state, and navigation callback.
- `SidebarNav` composes both desktop layers and exposes `data-width="264|80"`.
- `Breadcrumbs` receives member ID and role so its category link uses the same validated recent/default destination as the primary rail.

- [ ] **Step 1: Write failing desktop hierarchy tests**

```tsx
test("shows five primary categories and only the active category children", () => {
  renderAdminSidebar("/workspaces/workspace-1/contents");
  expect(screen.getByRole("navigation", { name: "功能大类" })).toBeVisible();
  expect(screen.getByRole("navigation", { name: "内容运营功能" })).toBeVisible();
  expect(screen.getByRole("link", { name: "内容库" })).toBeVisible();
  expect(screen.queryByRole("link", { name: "生成中心" })).toBeNull();
  expect(screen.queryByRole("link", { name: "工作区设置" })).toBeNull();
});

test("uses 264px expanded and 80px collapsed widths", async () => {
  render(<WorkspaceShell context={context}>页面</WorkspaceShell>);
  expect(screen.getByRole("complementary")).toHaveAttribute("data-width", "264");
  await userEvent.click(screen.getByRole("button", { name: "收起功能列表" }));
  expect(screen.getByRole("complementary")).toHaveAttribute("data-width", "80");
  expect(screen.getByRole("navigation", { name: "功能大类" })).toBeVisible();
  expect(screen.queryByRole("navigation", { name: "内容运营功能" })).toBeNull();
});

test("shows workspace category and current page in breadcrumbs", () => {
  renderShellAt("/workspaces/workspace-1/contents");
  expect(screen.getByRole("navigation", { name: "面包屑" })).toHaveTextContent(
    "合成运营工作区 / 运营 / 内容库",
  );
});
```

- [ ] **Step 2: Run the focused test and confirm RED**

```bash
pnpm --filter web test:run -- src/components/workbench/workspace-shell.test.tsx
```

Expected: width, navigation labels, and breadcrumb assertions fail.

- [ ] **Step 3: Implement the 80px primary rail**

Render visible category links with visible Chinese labels, decorative SVG icons, `aria-current` for the active category, and tooltips as supplemental help only. Clicking another category resolves the validated recent child from Task 1 or the role-safe default, then uses `workbenchHref`.

When the current route already belongs to the category, keep the current href. Update recent-child storage only after a canonical route is active.

- [ ] **Step 4: Implement the 184px secondary navigation**

Render the active category title and only its allowed children. The secondary column owns the `收起功能列表` button. Preserve `aria-current="page"`, stable focus styles, and current scope using existing `buildWorkspaceHref` behavior where applicable.

The desktop wrapper widths must be:

```tsx
const sidebarWidth = collapsed ? 80 : 264;
const sidebarClass = collapsed ? "w-[80px]" : "w-[264px]";
const contentClass = collapsed ? "pl-[80px]" : "pl-[264px]";
```

- [ ] **Step 5: Implement three-level breadcrumbs without changing routes**

For a matched route, render:

```text
workspace / category / page
```

The workspace link targets the workbench overview. The category link targets the current/last/default category child using the same validated navigation helper. The page segment uses `aria-current="page"`.

- [ ] **Step 6: Run focused and full Web verification**

```bash
pnpm --filter web test:run -- src/components/workbench/workspace-shell.test.tsx
pnpm --filter web test:run
pnpm --filter web lint
pnpm --filter web typecheck
pnpm --filter web build
git diff --check
```

Expected: all pass and no private route changes.

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/components/workbench/primary-nav.tsx apps/web/src/components/workbench/secondary-nav.tsx apps/web/src/components/workbench/sidebar-nav.tsx apps/web/src/components/workbench/workspace-shell.tsx apps/web/src/components/workbench/breadcrumbs.tsx apps/web/src/components/workbench/workspace-topbar.tsx apps/web/src/components/workbench/workspace-shell.test.tsx
git commit -m "feat: add two-level desktop workbench navigation"
```

---

### Task 3: Two-Step Mobile Drawer and Navigation Acceptance

**Files:**
- Modify: `apps/web/src/components/workbench/mobile-drawer.tsx`
- Modify: `apps/web/src/components/workbench/workspace-shell.test.tsx`
- Modify: `tests/e2e/workbench-navigation.spec.ts`
- Modify: `tests/e2e/workbench-mobile.spec.ts`
- Modify: `tests/e2e/workbench-visual.spec.ts`
- Modify: `docs/acceptance/workbench-route-inventory.md`
- Modify: `docs/acceptance/evidence/workbench-automated-acceptance-2026-07-30.md`

**Interfaces:**
- Consumes Task 1 categories and Task 2 child navigation.
- Produces mobile state `categories | children`.
- Preserves `MobileDrawer` focus trap, Escape close, background inertness, navigation close, and return focus.

- [ ] **Step 1: Write failing mobile two-step tests**

```tsx
test("shows categories first and one child list after selection", async () => {
  setMobileViewport(true);
  renderShellAt("/workspaces/workspace-1");
  await userEvent.click(screen.getByRole("button", { name: "打开主导航" }));
  expect(screen.getByRole("navigation", { name: "功能大类" })).toBeVisible();
  expect(screen.queryByRole("link", { name: "内容库" })).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "运营" }));
  expect(screen.getByRole("button", { name: "返回全部分类" })).toBeVisible();
  expect(screen.getByRole("link", { name: "内容库" })).toBeVisible();
});

test("opens a deep link at its current category children", async () => {
  setMobileViewport(true);
  renderShellAt("/workspaces/workspace-1/facts");
  await userEvent.click(screen.getByRole("button", { name: "打开主导航" }));
  expect(screen.getByText("策略资产")).toBeVisible();
  expect(screen.getByRole("link", { name: "事实资料" })).toHaveAttribute(
    "aria-current",
    "page",
  );
});
```

- [ ] **Step 2: Run the focused test and confirm RED**

```bash
pnpm --filter web test:run -- src/components/workbench/workspace-shell.test.tsx
```

- [ ] **Step 3: Implement mobile category and child states**

On root workbench route, open at `categories`. On a matched non-root route, open at the active category `children`. Category selection switches the drawer view without navigating the page; child selection navigates and closes the drawer. `返回全部分类` returns to category selection.

Keep the close button as initial focus, retain the existing focus trap and Escape behavior, and prevent the background from becoming interactive.

- [ ] **Step 4: Update role, route, mobile, and visual E2E**

Change navigation assertions so they select a category before expecting its children. Add:

- Admin 5 categories / 16 children across categories.
- Editor 5 categories / 13 children.
- Viewer 4 categories / 9 children and no management category.
- default child navigation for all five categories.
- recent-child restoration.
- 390px two-step drawer and deep-link child view.
- expanded 264px, collapsed 80px, and mobile screenshots.

Keep all canonical route and safe `returnTo` assertions.

- [ ] **Step 5: Update acceptance evidence**

Document the new hierarchy, unchanged route/role totals, desktop/mobile behavior, and visual baseline names. Keep Task 9B as:

```text
not_run: independent_non_developer_session_pending
```

Do not fabricate participant evidence.

- [ ] **Step 6: Run the complete affected verification**

```bash
pnpm --filter web test:run
pnpm --filter web lint
pnpm --filter web typecheck
pnpm --filter web build
pnpm --dir tests/e2e test -- workbench-navigation.spec.ts workbench-mobile.spec.ts workbench-visual.spec.ts full-loop.spec.ts
git diff --check
```

Then run the repository’s existing secret scan. No API, OpenAPI, migration, Extension, model, or database change is expected.

- [ ] **Step 7: Review screenshots against the approved mockup**

Inspect every new baseline and verify:

- only five primary categories are simultaneously visible;
- only the active category children are visible;
- current category and page are unambiguous;
- 264px expanded navigation does not break tables or dashboards;
- 80px collapsed state keeps readable category labels;
- 390px drawer never renders two columns;
- no text overlap, truncation, horizontal overflow, or dark legacy surface appears.

- [ ] **Step 8: Commit**

```bash
git add apps/web/src/components/workbench/mobile-drawer.tsx apps/web/src/components/workbench/workspace-shell.test.tsx tests/e2e/workbench-navigation.spec.ts tests/e2e/workbench-mobile.spec.ts tests/e2e/workbench-visual.spec.ts docs/acceptance/workbench-route-inventory.md docs/acceptance/evidence/workbench-automated-acceptance-2026-07-30.md
git commit -m "test: accept two-level workbench navigation"
```

---

## Final Completion Gate

The navigation change is complete only when:

1. All three tasks are committed and the worktree is clean.
2. Admin/Editor/Viewer retain 16/13/9 route access.
3. Desktop shows five categories plus only one child list.
4. Collapsed desktop shows the 80px category rail.
5. Mobile uses a two-step drawer with preserved focus and Escape behavior.
6. All canonical routes, scope, `returnTo`, permission, and deep-link tests pass.
7. Web unit, lint, typecheck, production build, affected E2E, visual review, and secret scan pass.
8. Task 9B remains pending until a real independent participant uses the revised navigation.
