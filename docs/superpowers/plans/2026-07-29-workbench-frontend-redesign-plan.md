# Operations Workbench Frontend Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the disconnected private workspace pages with one modular, discoverable operations workbench while preserving every existing product rule, permission boundary, API invariant, and public Demo isolation guarantee.

**Architecture:** Keep the current Next.js 16, React 19, FastAPI modular monolith and generated OpenAPI types. Add a small `workbench` read-model module for navigation context and cross-module operational queues; all benchmark, analysis, fact, risk, generation, and permission decisions remain in their existing API modules. Build one shared workspace layout, route-scoped pages, URL-backed filters, and reusable accessible UI primitives without adding a third-party component library.

**Tech Stack:** Next.js 16 App Router, React 19, TypeScript 5, Tailwind CSS 4, ECharts 6, Vitest/Testing Library, Playwright, FastAPI, Pydantic, SQLAlchemy, PostgreSQL, generated OpenAPI TypeScript schemas.

## Global Constraints

- Execute in an isolated worktree created from the commit containing this plan, using branch `codex/workbench-redesign`; the source checkout contains unrelated local edits that must not be staged, overwritten, or copied.
- Read `docs/superpowers/specs/2026-07-29-workbench-frontend-redesign-design.md` and `docs/superpowers/specs/2026-07-20-operations-ai-platform-design.md` before Task 1.
- Do not change dynamic benchmark, fact conflict, RiskRAG, generation, retention, model governance, or permission algorithms.
- Douyin and Xiaohongshu metrics, benchmarks, filters, and evaluation results must remain separate.
- The all-account workbench may aggregate counts, statuses, completeness, and closed-loop state; it must never aggregate cross-platform business metric values or trends.
- Every private route uses `/workspaces/{workspace_id}` and the shared `WorkspaceShell`.
- Preserve existing public `/demo` and `/enter` behavior and keep Demo resources isolated and read-only.
- Keep old private deep links working through internal redirects until all links and tests use the canonical routes.
- Use the system Chinese font stack; add no online font and no new UI component dependency.
- Desktop receives complete workflows. Mobile supports viewing, feedback, confirmation, and light actions; unsupported complex workflows render `DesktopOnlyNotice`.
- Core actions may not be hidden under “更多操作”; each page has at most one primary button.
- Frontend code consumes generated OpenAPI types and does not reproduce backend business decisions.
- All screenshots, fixtures, and E2E data are synthetic and contain no invite code, key, real copy, or private document.
- Finish each task with focused tests, repository-level static checks appropriate to the changed surface, and one commit.

## File Structure

New shared frontend files:

- `apps/web/src/components/workbench/workspace-shell.tsx`: desktop/sidebar/mobile workspace frame.
- `apps/web/src/components/workbench/sidebar-nav.tsx`: role-aware grouped primary navigation.
- `apps/web/src/components/workbench/workspace-topbar.tsx`: breadcrumbs, scope filters, role menu, and task alert.
- `apps/web/src/components/workbench/scope-query.ts`: validated URL platform/account scope.
- `apps/web/src/components/workbench/navigation.ts`: canonical route and navigation group definitions.
- `apps/web/src/components/workbench/ui.tsx`: small accessible page, card, badge, state, table, tab, and notice primitives.
- `apps/web/src/components/workbench/workbench-overview.tsx`: workspace operational overview.
- `apps/web/src/components/workbench/content-detail-tabs.tsx`: five-tab content detail container.
- `apps/web/src/components/workbench/generation-wizard.tsx`: five-step generation flow.
- `apps/web/src/lib/workbench-api.ts`: typed workbench read-model client.

New backend files:

- `apps/api/app/modules/workbench/__init__.py`: module marker.
- `apps/api/app/modules/workbench/schemas.py`: navigation, overview, analysis queue, and preflight queue response schemas.
- `apps/api/app/modules/workbench/service.py`: workspace-scoped read-model aggregation only.
- `apps/api/app/modules/workbench/router.py`: read-only workbench endpoints.
- `apps/api/tests/workbench/test_workbench_api.py`: permission, isolation, platform separation, and response tests.

New or canonical Next.js routes:

- `apps/web/src/app/workspaces/[workspaceId]/layout.tsx`
- `apps/web/src/app/workspaces/[workspaceId]/page.tsx`
- `apps/web/src/app/workspaces/[workspaceId]/accounts/page.tsx`
- `apps/web/src/app/workspaces/[workspaceId]/columns/page.tsx`
- `apps/web/src/app/workspaces/[workspaceId]/analysis/page.tsx`
- `apps/web/src/app/workspaces/[workspaceId]/styles/page.tsx`
- `apps/web/src/app/workspaces/[workspaceId]/preflight/page.tsx`
- `apps/web/src/app/workspaces/[workspaceId]/data-management/exports/page.tsx`
- `apps/web/src/app/workspaces/[workspaceId]/data-management/trash/page.tsx`
- `apps/web/src/app/workspaces/[workspaceId]/settings/page.tsx`

Existing feature components remain in their domain folders and are restyled or composed by the canonical pages instead of being duplicated.

---

### Task 1: Design Tokens and Accessible UI Primitives

**Files:**
- Modify: `apps/web/src/app/globals.css`
- Create: `apps/web/src/components/workbench/ui.tsx`
- Create: `apps/web/src/components/workbench/ui.test.tsx`
- Modify: `apps/web/src/app/layout-source.test.ts`

**Interfaces:**
- Produces: `PageHeader`, `Panel`, `StatusBadge`, `EmptyState`, `ErrorState`, `PermissionNotice`, `DesktopOnlyNotice`, `Skeleton`, `DetailTabs`, and `DataTableFrame`.
- Produces CSS variables `--canvas`, `--surface`, `--text-primary`, `--text-secondary`, `--border`, `--brand`, `--success`, `--warning`, `--danger`, and `--info`.
- Consumes no product data and makes no API calls.

- [ ] **Step 1: Create failing primitive and token tests**

```tsx
it("renders status text in addition to color", () => {
  render(<StatusBadge tone="danger">高风险</StatusBadge>);
  expect(screen.getByText("高风险")).toHaveAttribute("data-tone", "danger");
});

it("explains desktop-only actions", () => {
  render(<DesktopOnlyNotice action="完整 ZIP 恢复" />);
  expect(screen.getByText(/请在电脑端继续完整 ZIP 恢复/)).toBeVisible();
});

it("keeps one h1 in PageHeader", () => {
  const { container } = render(<PageHeader title="内容库" description="管理已发布内容" />);
  expect(container.querySelectorAll("h1")).toHaveLength(1);
});
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run:

```bash
pnpm --filter web test:run -- src/components/workbench/ui.test.tsx src/app/layout-source.test.ts
```

Expected: failure because `ui.tsx` and the light workbench variables do not exist.

- [ ] **Step 3: Implement the primitives and fixed visual variables**

Use this public surface:

```tsx
export type StatusTone = "neutral" | "info" | "success" | "warning" | "danger";

export function StatusBadge(props: {
  tone: StatusTone;
  children: React.ReactNode;
}): React.ReactElement;

export function PageHeader(props: {
  title: string;
  description?: string;
  primaryAction?: React.ReactNode;
  secondaryActions?: React.ReactNode;
}): React.ReactElement;

export function DesktopOnlyNotice(props: {
  action: string;
}): React.ReactElement;
```

Set the base variables exactly:

```css
:root {
  --canvas: #f5f7fb;
  --surface: #ffffff;
  --text-primary: #1b2430;
  --text-secondary: #6f7b89;
  --border: #e2e6ec;
  --brand: #6d55dc;
}
```

Remove the automatic dark media override. Preserve visible focus, `prefers-reduced-motion`, system fonts, and WCAG-AA-friendly state contrast.

- [ ] **Step 4: Run focused and frontend static checks**

```bash
pnpm --filter web test:run -- src/components/workbench/ui.test.tsx src/app/layout-source.test.ts
pnpm --filter web lint
pnpm --filter web typecheck
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/app/globals.css apps/web/src/app/layout-source.test.ts apps/web/src/components/workbench/ui.tsx apps/web/src/components/workbench/ui.test.tsx
git commit -m "feat: add workbench design foundations"
```

---

### Task 2: Workspace-Scoped Workbench Read Models

**Files:**
- Create: `apps/api/app/modules/workbench/__init__.py`
- Create: `apps/api/app/modules/workbench/schemas.py`
- Create: `apps/api/app/modules/workbench/service.py`
- Create: `apps/api/app/modules/workbench/router.py`
- Create: `apps/api/tests/workbench/test_workbench_api.py`
- Modify: `apps/api/app/main.py`
- Modify: `packages/shared-schemas/openapi.json`
- Modify: `packages/shared-schemas/src/schema.ts`

**Interfaces:**
- Produces `GET /v1/workspaces/{workspace_id}/workbench/context`.
- Produces `GET /v1/workspaces/{workspace_id}/workbench/overview`.
- Produces `GET /v1/workspaces/{workspace_id}/workbench/analysis-queue`.
- Produces `GET /v1/workspaces/{workspace_id}/workbench/preflight-queue`.
- Every endpoint consumes the existing authenticated `WorkspaceContext`, returns 404 across workspaces, and is read-only.

- [ ] **Step 1: Write failing API isolation and separation tests**

```python
def test_overview_separates_accounts_and_never_sums_platform_metrics(
    client, seeded_workspace_session
):
    response = client.get(
        f"/v1/workspaces/{seeded_workspace_session.workspace_id}/workbench/overview"
    )
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"data_status", "attention", "next_action", "accounts"}
    assert {item["platform"] for item in payload["accounts"]} == {"douyin", "xiaohongshu"}
    assert "total_views" not in payload
    assert "combined_metrics" not in payload


def test_workbench_cross_workspace_is_404(client, foreign_workspace_session):
    response = client.get(
        f"/v1/workspaces/{foreign_workspace_session.other_workspace_id}/workbench/context"
    )
    assert response.status_code == 404
```

Also assert:

- viewer can read all four endpoints;
- Demo session cannot read a private workspace;
- analysis and preflight filters reject an account from another workspace;
- `platform=douyin` never returns Xiaohongshu rows;
- queue rows expose IDs, enums, bounded counts, versions, and safe summaries, never full prompts, keys, OCR source text, or document bodies.

- [ ] **Step 2: Run the focused API test and confirm RED**

```bash
cd apps/api
.venv/bin/pytest tests/workbench/test_workbench_api.py -q
```

Expected: route/module import or 404 failures because the workbench module does not exist.

- [ ] **Step 3: Define strict response schemas**

Use explicit fields:

```python
class WorkbenchContextRead(BaseModel):
    workspace_id: UUID
    workspace_name: str
    member_id: UUID
    member_display_name: str
    role: Literal["admin", "editor", "viewer"]
    accounts: list[WorkbenchAccountOption]
    failed_task_count: int = Field(ge=0)


class WorkbenchOverviewRead(BaseModel):
    data_status: WorkbenchDataStatus
    attention: WorkbenchAttentionCounts
    next_action: WorkbenchNextAction | None
    accounts: list[WorkbenchAccountCard]
```

`WorkbenchAccountCard` contains `account_id`, `platform`, `name`, `content_type_counts`, `completeness`, `pending_analysis_count`, `open_risk_count`, and `has_current_week_closed_loop`. It contains no cross-platform metric value.

- [ ] **Step 4: Implement one read-only service with early workspace/platform filters**

```python
class WorkbenchService:
    def get_overview(
        self,
        session: Session,
        context: WorkspaceContext,
    ) -> WorkbenchOverviewRead:
        accounts = self._account_cards(session, context.workspace_id)
        return WorkbenchOverviewRead(
            data_status=self._data_status(session, context.workspace_id),
            attention=self._attention(session, context.workspace_id),
            next_action=self._next_action(session, context.workspace_id),
            accounts=accounts,
        )
```

The service may call existing query helpers, but must not reimplement benchmark percentiles, RiskRAG severity, fact precedence, or generation gates. Register the router in `app/main.py`.

- [ ] **Step 5: Regenerate contracts and run all relevant checks**

Use the repository’s existing OpenAPI generation commands discovered from CI/package scripts, then run:

```bash
cd apps/api
.venv/bin/pytest tests/workbench/test_workbench_api.py -q
.venv/bin/pytest -q
.venv/bin/ruff check app tests
.venv/bin/mypy app
cd ../..
pnpm --filter web typecheck
git diff --check
```

Expected: workbench tests and the full API suite pass; generated OpenAPI and TypeScript types have no drift.

- [ ] **Step 6: Commit**

```bash
git add apps/api/app/main.py apps/api/app/modules/workbench apps/api/tests/workbench packages/shared-schemas
git commit -m "feat: expose isolated workbench read models"
```

---

### Task 3: Shared Workspace Shell, Navigation, and Scope

**Files:**
- Create: `apps/web/src/app/workspaces/[workspaceId]/layout.tsx`
- Create: `apps/web/src/components/workbench/navigation.ts`
- Create: `apps/web/src/components/workbench/scope-query.ts`
- Create: `apps/web/src/components/workbench/sidebar-nav.tsx`
- Create: `apps/web/src/components/workbench/workspace-topbar.tsx`
- Create: `apps/web/src/components/workbench/workspace-shell.tsx`
- Create: `apps/web/src/components/workbench/workspace-shell.test.tsx`
- Create: `apps/web/src/lib/workbench-api.ts`

**Interfaces:**
- Consumes `WorkbenchContextRead` from Task 2.
- Produces `parseWorkbenchScope(searchParams, accounts): WorkbenchScope`.
- Produces `buildWorkspaceHref(workspaceId, pathname, scope, returnTo?): string`.
- Produces a role-aware `WORKBENCH_NAV_GROUPS` constant used by all navigation tests.

- [ ] **Step 1: Write failing navigation, role, scope, and mobile tests**

```tsx
it("shows every admin module and hides admin-only modules from viewers", async () => {
  const { rerender } = renderShell({ role: "admin" });
  expect(screen.getByRole("link", { name: "风控知识库" })).toBeVisible();
  expect(screen.getByRole("link", { name: "回收站" })).toBeVisible();
  rerender(renderShellElement({ role: "viewer" }));
  expect(screen.queryByRole("link", { name: "风控知识库" })).not.toBeInTheDocument();
});

it("keeps compatible platform and account scope in the URL", () => {
  expect(
    buildWorkspaceHref("workspace-1", "/contents", {
      platform: "douyin",
      accountId: "account-1",
    }),
  ).toBe("/workspaces/workspace-1/contents?platform=douyin&account=account-1");
});

it("opens the sidebar as a modal drawer below 768px", async () => {
  renderShell({ viewport: 390 });
  await userEvent.click(screen.getByRole("button", { name: "打开主导航" }));
  expect(screen.getByRole("dialog", { name: "主导航" })).toBeVisible();
});
```

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
pnpm --filter web test:run -- src/components/workbench/workspace-shell.test.tsx
```

Expected: missing module failures.

- [ ] **Step 3: Implement canonical grouped navigation**

Define these stable groups in `navigation.ts`:

```ts
export const WORKBENCH_NAV_GROUPS = [
  ["工作台", ["工作台总览"]],
  ["内容运营", ["账号仪表盘", "栏目与活动", "内容库", "数据导入", "分析中心"]],
  ["策略资产", ["爆款素材库", "账号风格", "事实资料"]],
  ["AI 创作", ["生成中心", "发布前检查"]],
  ["治理与数据", ["风控知识库", "导出与备份", "回收站"]],
  ["工作区管理", ["后台任务", "工作区设置"]],
] as const;
```

Attach exact canonical routes from the design spec and an `allowedRoles` array to every item. Core navigation items must remain visible when the sidebar is expanded and cannot live in an overflow menu.

- [ ] **Step 4: Implement safe URL scope and shell behavior**

`parseWorkbenchScope` must:

- accept only `douyin`, `xiaohongshu`, or absent platform;
- accept an account only when it belongs to the current workspace and matches the selected platform;
- clear incompatible account scope;
- never accept an external `returnTo`;
- keep sidebar preference under `operations-ai:sidebar:{memberId}` with value `expanded` or `collapsed`.

The topbar renders breadcrumbs, platform/account selectors, role, member menu, help, and failed-task alert. The shell uses `<aside>`, `<nav aria-label="主导航">`, `<header>`, and `<main id="main-content">`.

- [ ] **Step 5: Run tests, lint, typecheck, and production build**

```bash
pnpm --filter web test:run -- src/components/workbench/workspace-shell.test.tsx
pnpm --filter web lint
pnpm --filter web typecheck
pnpm --filter web build
```

Expected: all pass and every existing private page compiles inside the shared layout.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/app/workspaces/[workspaceId]/layout.tsx apps/web/src/components/workbench apps/web/src/lib/workbench-api.ts
git commit -m "feat: add role-aware workspace shell"
```

---

### Task 4: Workbench Overview, Accounts, and Columns

**Files:**
- Create: `apps/web/src/app/workspaces/[workspaceId]/page.tsx`
- Create: `apps/web/src/app/workspaces/[workspaceId]/accounts/page.tsx`
- Create: `apps/web/src/app/workspaces/[workspaceId]/columns/page.tsx`
- Create: `apps/web/src/components/workbench/workbench-overview.tsx`
- Create: `apps/web/src/components/workbench/workbench-overview.test.tsx`
- Create: `apps/web/src/components/account/account-list.tsx`
- Create: `apps/web/src/components/account/columns-center.tsx`
- Modify: `apps/web/src/app/workspaces/[workspaceId]/accounts/[accountId]/page.tsx`
- Modify: `apps/web/src/components/charts/account-dashboard.tsx`
- Modify: `apps/web/src/components/charts/charts.test.tsx`

**Interfaces:**
- Consumes `loadWorkbenchOverview(workspaceId)` and existing account/dashboard APIs.
- Produces `WorkbenchOverview`, `AccountList`, and `ColumnsCenter`.
- Preserves account dashboard chart gates in the API response; the UI renders the provided eligibility/reason rather than recomputing it.

- [ ] **Step 1: Write failing workbench and account-range tests**

```tsx
it("shows operational counts but no combined metric in all-account scope", () => {
  render(<WorkbenchOverview overview={twoPlatformOverview} workspaceId="workspace-1" />);
  expect(screen.getByText("2 个账号缺少推荐快照")).toBeVisible();
  expect(screen.queryByText("总播放量")).not.toBeInTheDocument();
  expect(screen.queryByText("综合趋势")).not.toBeInTheDocument();
});

it("shows why an ineligible account chart is hidden", () => {
  render(<AccountDashboard data={oneSnapshotDashboard} />);
  expect(screen.getByText(/至少需要 2 条有效快照/)).toBeVisible();
  expect(screen.queryByRole("img", { name: /趋势/ })).not.toBeInTheDocument();
});
```

Add tests that an account card links to the matching account dashboard and a column override visibly distinguishes `继承账号默认` from `临时覆盖`.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
pnpm --filter web test:run -- src/components/workbench/workbench-overview.test.tsx src/components/charts/charts.test.tsx
```

- [ ] **Step 3: Implement the operational command center**

Render in this order:

1. data status;
2. attention queues;
3. one highest-priority next action;
4. per-account cards;
5. shortcuts for create content, import, analysis, and generation.

Account cards show platform, name, completeness, pending analysis, open risk, and closed-loop status. Do not derive or display summed views, exposure, CTR, or a combined score.

- [ ] **Step 4: Implement account and column pages**

The account list is the stable landing for “账号仪表盘”. The single-account page keeps 4–6 target cards, one trend, benchmark bands, anomalies, reason hypotheses, confidence, and next actions. Save hidden optional dashboard modules in a local presentation preference and provide `恢复默认布局`.

The column page lists scope, effective time, inheritance, override count, and current version; editing shows account default, temporary override, and post-expiry restoration for target, weights, benchmark, style, and generation preset.

- [ ] **Step 5: Verify focused, frontend, and account API regressions**

```bash
pnpm --filter web test:run -- src/components/workbench/workbench-overview.test.tsx src/components/charts/charts.test.tsx src/components/account
pnpm --filter web lint
pnpm --filter web typecheck
cd apps/api
.venv/bin/pytest tests/content tests/metrics tests/workbench -q
```

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/app/workspaces/[workspaceId]/page.tsx apps/web/src/app/workspaces/[workspaceId]/accounts apps/web/src/app/workspaces/[workspaceId]/columns apps/web/src/components/workbench/workbench-overview* apps/web/src/components/account apps/web/src/components/charts
git commit -m "feat: deliver workbench account operations"
```

---

### Task 5: Content Library and Five-Tab Content Detail

**Files:**
- Modify: `apps/web/src/app/workspaces/[workspaceId]/contents/page.tsx`
- Modify: `apps/web/src/app/workspaces/[workspaceId]/contents/[contentId]/page.tsx`
- Modify: `apps/web/src/components/content/content-detail.tsx`
- Modify: `apps/web/src/components/content/content-detail.test.tsx`
- Create: `apps/web/src/components/content/content-list.tsx`
- Create: `apps/web/src/components/content/content-list.test.tsx`
- Create: `apps/web/src/components/workbench/content-detail-tabs.tsx`
- Modify: `apps/web/src/app/workspaces/[workspaceId]/contents/[contentId]/analysis/page.tsx`

**Interfaces:**
- Consumes existing content, snapshot, analysis, risk scan, and generation APIs.
- Produces canonical detail query `tab=overview|snapshots|analysis|risk|generation`.
- Produces safe internal `returnTo` encoded from the current content-list or queue URL.

- [ ] **Step 1: Write failing URL-filter and detail-tab tests**

```tsx
it("serializes every content drill-down filter", async () => {
  render(<ContentList initialQuery="?platform=douyin&status=published&page=2&sort=-published_at" />);
  await userEvent.selectOptions(screen.getByLabelText("栏目"), "column-1");
  expect(currentHref()).toContain("column=column-1");
  expect(currentHref()).toContain("platform=douyin");
  expect(currentHref()).toContain("page=1");
});

it.each(["概览", "数据快照", "分析", "风控", "生成记录"])(
  "renders the %s detail tab",
  (label) => {
    render(<ContentDetailTabs content={contentFixture} initialTab={labelToTab[label]} />);
    expect(screen.getByRole("tab", { name: label })).toBeVisible();
  },
);

it("rejects an external return target", () => {
  expect(safeReturnTo("https://attacker.example", "workspace-1")).toBeNull();
});
```

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
pnpm --filter web test:run -- src/components/content/content-list.test.tsx src/components/content/content-detail.test.tsx
```

- [ ] **Step 3: Implement the complete content filter bar and responsive list**

Store `platform`, `account`, `column`, `contentType`, `status`, `maturity`, `query`, `sort`, and `page` in the URL. Desktop rows show cover, title, scope, lifecycle, publish time, maturity, completeness, analysis, risk, and next action. Mobile cards show the same critical statuses without squeezing them into an unreadable table.

- [ ] **Step 4: Implement the five-tab detail**

The header shows breadcrumb, safe return, title, platform, account, column, lifecycle, “生成同类内容”, and low-frequency overflow actions. Each tab must render its own loading, empty, error, permission, and insufficient-sample state.

Redirect the old `/contents/{content_id}/analysis` route internally to `/contents/{content_id}?tab=analysis`, preserving only validated workspace-local return context.

- [ ] **Step 5: Run focused tests and content E2E**

```bash
pnpm --filter web test:run -- src/components/content
pnpm --filter web lint
pnpm --filter web typecheck
pnpm --dir tests/e2e test -- content-detail.spec.ts
```

Expected: tabs, lifecycle, scope, and return state pass.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/app/workspaces/[workspaceId]/contents apps/web/src/components/content apps/web/src/components/workbench/content-detail-tabs.tsx
git commit -m "feat: unify content library and detail workflow"
```

---

### Task 6: Import Center and Analysis Queue

**Files:**
- Modify: `apps/web/src/app/workspaces/[workspaceId]/imports/page.tsx`
- Create: `apps/web/src/app/workspaces/[workspaceId]/analysis/page.tsx`
- Create: `apps/web/src/components/imports/import-center.tsx`
- Create: `apps/web/src/components/imports/import-center.test.tsx`
- Create: `apps/web/src/components/analysis/analysis-queue.tsx`
- Create: `apps/web/src/components/analysis/analysis-queue.test.tsx`
- Modify: `apps/web/src/lib/import-api.ts`
- Modify: `apps/web/src/lib/analysis-api.ts`

**Interfaces:**
- Consumes existing manual, Excel/CSV, screenshot, and extension capture flows.
- Consumes `GET .../workbench/analysis-queue` from Task 2.
- Produces one `ImportCenter` with method selection and a shared preview/confirm lifecycle.
- Produces queue links to `?tab=analysis&returnTo={safeInternalPath}`.

- [ ] **Step 1: Write failing import-state and analysis-queue tests**

```tsx
it.each(["手动录入", "Excel / CSV", "截图识别", "Capture Extension"])(
  "shows the %s import method",
  (name) => {
    render(<ImportCenter workspaceId="workspace-1" />);
    expect(screen.getByRole("button", { name })).toBeVisible();
  },
);

it("does not weaken unknown and low-confidence fields", () => {
  render(<ImportCenter workspaceId="workspace-1" batch={lowConfidenceBatch} />);
  expect(screen.getByText("低置信度，必须人工确认")).toBeVisible();
  expect(screen.getByText("未知字段")).toBeVisible();
});

it("opens a queue item in the content analysis tab", () => {
  render(<AnalysisQueue rows={analysisRows} />);
  expect(screen.getByRole("link", { name: /查看分析/ })).toHaveAttribute(
    "href",
    expect.stringContaining("tab=analysis"),
  );
});
```

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
pnpm --filter web test:run -- src/components/imports/import-center.test.tsx src/components/analysis/analysis-queue.test.tsx
```

- [ ] **Step 3: Compose the unified import center**

All four methods follow `选择来源 → 上传/采集 → 暂存预览 → 修正 → 确认入库`. Reuse `ImportReview`, `ScreenshotReview`, and `ExtensionCaptureReview`; do not fork their validation or confirmation rules. Show new/update/duplicate/failure counts and a history section.

- [ ] **Step 4: Implement the analysis queue**

Provide tabs or status filters for pending, running, completed, insufficient sample, failed/configuration required, and suggestion pending adoption. Each row shows content scope, maturity, sample count, analysis version, issue, confidence, and next action.

- [ ] **Step 5: Run import, analysis, and E2E regressions**

```bash
pnpm --filter web test:run -- src/components/imports src/components/analysis src/app/workspaces/[workspaceId]/contents/[contentId]/analysis
pnpm --filter web lint
pnpm --filter web typecheck
cd apps/api
.venv/bin/pytest tests/imports tests/analysis tests/workbench -q
cd ../..
pnpm --dir tests/e2e test -- metrics-import-analysis.spec.ts extension-safe-capture.spec.ts
```

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/app/workspaces/[workspaceId]/imports apps/web/src/app/workspaces/[workspaceId]/analysis apps/web/src/components/imports apps/web/src/components/analysis apps/web/src/lib/import-api.ts apps/web/src/lib/analysis-api.ts
git commit -m "feat: expose import and analysis operations"
```

---

### Task 7: Strategy Assets—Viral, Style, and Facts

**Files:**
- Modify: `apps/web/src/app/workspaces/[workspaceId]/viral-library/page.tsx`
- Create: `apps/web/src/app/workspaces/[workspaceId]/styles/page.tsx`
- Modify: `apps/web/src/app/workspaces/[workspaceId]/styles/[accountId]/page.tsx`
- Modify: `apps/web/src/app/workspaces/[workspaceId]/facts/page.tsx`
- Modify: `apps/web/src/components/viral/viral-library.tsx`
- Modify: `apps/web/src/components/viral/viral-library.test.tsx`
- Modify: `apps/web/src/components/styles/style-profile-center.tsx`
- Modify: `apps/web/src/components/styles/style-profile-center.test.tsx`
- Modify: `apps/web/src/components/facts/fact-source-center.tsx`
- Modify: `apps/web/src/components/facts/fact-source-center.test.tsx`

**Interfaces:**
- Consumes existing viral, style, and fact API clients.
- Produces an account-selection landing for style profiles.
- Preserves the distinction between viral candidate, confirmed viral item, style sample, and confirmed fact.

- [ ] **Step 1: Write failing semantic-boundary tests**

```tsx
it("never presents a viral candidate as confirmed", () => {
  render(<ViralLibrary candidates={[candidate]} items={[]} />);
  expect(screen.getByText("候选，尚未进入素材库")).toBeVisible();
  expect(screen.queryByText("已确认爆款")).not.toBeInTheDocument();
});

it("separates title copy and cover style inheritance", () => {
  render(<StyleProfileCenter profile={styleFixture} />);
  expect(screen.getByRole("heading", { name: "标题风格" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "文案风格" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "封面风格" })).toBeVisible();
});

it("labels L5 visual inference as non-deterministic", () => {
  render(<FactSourceCenter source={l5Fixture} />);
  expect(screen.getByText("禁止仅凭视觉推测写入确定性文案")).toBeVisible();
});
```

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
pnpm --filter web test:run -- src/components/viral src/components/styles src/components/facts
```

- [ ] **Step 3: Restyle viral and style assets with explicit scope**

Viral rows show candidate/confirmed section, platform, account, type, benchmark scope, sample count, percentile, reason, confirmation audit, applicable scope, and generation reference count.

Style landing requires account selection. The detail page has separate title/copy/cover sections, current version, representative content, extracted traits, prohibited traits, last update, and column override status. Display “账号风格” and “爆款结构” as separate concepts.

- [ ] **Step 4: Restyle facts as source list plus fact list**

Sources show type, L1–L5, parse state, confirmation, conflict count, and scope. Fact rows show field/value, source location, level, confirmation, conflict, override audit, and visual-inference restriction. Add the controlled L4 web-search entry without allowing unconfirmed search results into generation.

- [ ] **Step 5: Verify domain tests**

```bash
pnpm --filter web test:run -- src/components/viral src/components/styles src/components/facts
pnpm --filter web lint
pnpm --filter web typecheck
cd apps/api
.venv/bin/pytest tests/analysis tests/style_facts -q
```

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/app/workspaces/[workspaceId]/viral-library apps/web/src/app/workspaces/[workspaceId]/styles apps/web/src/app/workspaces/[workspaceId]/facts apps/web/src/components/viral apps/web/src/components/styles apps/web/src/components/facts
git commit -m "feat: clarify reusable strategy assets"
```

---

### Task 8: Five-Step Generation and Publication Preflight

**Files:**
- Modify: `apps/web/src/app/workspaces/[workspaceId]/generation/page.tsx`
- Create: `apps/web/src/app/workspaces/[workspaceId]/preflight/page.tsx`
- Create: `apps/web/src/components/workbench/generation-wizard.tsx`
- Create: `apps/web/src/components/workbench/generation-wizard.test.tsx`
- Create: `apps/web/src/components/risk/preflight-queue.tsx`
- Create: `apps/web/src/components/risk/preflight-queue.test.tsx`
- Modify: `apps/web/src/components/generation/cover-editor/cover-editor.tsx`
- Modify: `apps/web/src/components/generation/cover-editor/cover-editor.test.tsx`
- Modify: `apps/web/src/components/risk/risk-report.tsx`
- Modify: `apps/web/src/components/risk/risk-report.test.tsx`

**Interfaces:**
- Consumes existing generation, facts, style, viral, model, OCR, and RiskRAG APIs.
- Consumes `GET .../workbench/preflight-queue` from Task 2.
- Produces wizard steps `scope`, `facts`, `references`, `generate`, and `review`.
- Does not change server-side fact or publication gates.

- [ ] **Step 1: Write failing wizard and gate tests**

```tsx
it("defaults all three style inheritance switches on", () => {
  render(<GenerationWizard fixture={generationFixture} />);
  expect(screen.getByRole("checkbox", { name: "沿用标题风格" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "沿用文案风格" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "沿用封面风格" })).toBeChecked();
});

it("blocks generation when confirmed facts conflict", async () => {
  render(<GenerationWizard fixture={conflictingFactsFixture} />);
  await goToFactsStep();
  expect(screen.getByRole("button", { name: "进入生成" })).toBeDisabled();
  expect(screen.getByText("请先处理高风险事实冲突")).toBeVisible();
});

it("shows the fixed risk disclaimer", () => {
  render(<RiskReport report={riskFixture} />);
  expect(screen.getByText("辅助判断，不保证通过平台审核")).toBeVisible();
});
```

Also cover 0–3 confirmed viral references, reference-image purpose, all four cover modes, low-confidence OCR, no active RAG evidence, provider `experimental`, and mobile desktop-only cover editing.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
pnpm --filter web test:run -- src/components/workbench/generation-wizard.test.tsx src/components/risk/preflight-queue.test.tsx src/components/generation/cover-editor src/components/risk/risk-report.test.tsx
```

- [ ] **Step 3: Implement the five-step state machine**

Use:

```ts
export type GenerationStep =
  | "scope"
  | "facts"
  | "references"
  | "generate"
  | "review";

export type GenerationWizardState = {
  step: GenerationStep;
  accountId: string | null;
  columnId: string | null;
  objectiveId: string | null;
  inheritTitleStyle: boolean;
  inheritCopyStyle: boolean;
  inheritCoverStyle: boolean;
  viralReferenceIds: string[];
  factSourceIds: string[];
};
```

Keep the server as authority for whether a transition may generate or save. The desktop summary shows scope, facts, styles, viral references, provider/contract, and risk state without secrets.

- [ ] **Step 4: Implement the global preflight queue**

Filters are pending scan, high-risk blocked, low-confidence OCR, no active RAG evidence, modified awaiting rescan, and manually confirmed. Every row retains platform/account scope and links to the content `risk` tab with safe return context.

- [ ] **Step 5: Run generation, RiskRAG, and E2E regressions**

```bash
pnpm --filter web test:run -- src/components/workbench/generation-wizard.test.tsx src/components/generation src/components/risk
pnpm --filter web lint
pnpm --filter web typecheck
cd apps/api
.venv/bin/pytest tests/generation tests/risk_rag tests/style_facts -q
cd ../..
pnpm --dir tests/e2e test -- generation.spec.ts risk-rag.spec.ts
```

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/app/workspaces/[workspaceId]/generation apps/web/src/app/workspaces/[workspaceId]/preflight apps/web/src/components/workbench/generation-wizard* apps/web/src/components/generation apps/web/src/components/risk
git commit -m "feat: make generation and preflight discoverable"
```

---

### Task 9: Governance, Data Management, Settings, and Demo

**Files:**
- Modify: `apps/web/src/app/workspaces/[workspaceId]/risk-knowledge/page.tsx`
- Create: `apps/web/src/app/workspaces/[workspaceId]/data-management/exports/page.tsx`
- Create: `apps/web/src/app/workspaces/[workspaceId]/data-management/trash/page.tsx`
- Create: `apps/web/src/app/workspaces/[workspaceId]/settings/page.tsx`
- Modify: `apps/web/src/app/workspaces/[workspaceId]/settings/jobs/page.tsx`
- Modify: `apps/web/src/app/workspaces/[workspaceId]/settings/members/page.tsx`
- Modify: `apps/web/src/app/workspaces/[workspaceId]/settings/models/page.tsx`
- Create: `apps/web/src/components/exports/export-backup-center.tsx`
- Create: `apps/web/src/components/exports/export-backup-center.test.tsx`
- Create: `apps/web/src/components/exports/trash-center.tsx`
- Create: `apps/web/src/components/exports/trash-center.test.tsx`
- Create: `apps/web/src/components/workspace/settings-nav.tsx`
- Modify: `apps/web/src/components/operations/job-operations.tsx`
- Modify: `apps/web/src/components/demo-workspace.tsx`
- Modify: `apps/web/src/components/demo-workspace.test.tsx`

**Interfaces:**
- Consumes existing risk administration, export/restore, deletion/retention, operations, members, and model APIs.
- Produces one settings secondary navigation with overview, members, accounts, metrics, models/budget, retention, and dangerous operations.
- Demo reuses visual primitives but never the private session or paid-operation clients.

- [ ] **Step 1: Write failing governance and Demo boundary tests**

```tsx
it("distinguishes every backup type and restore preview action", () => {
  render(<ExportBackupCenter fixture={exportFixture} role="admin" />);
  for (const label of ["CSV", "Markdown", "JSON 轻量备份", "ZIP 完整备份"]) {
    expect(screen.getByText(label)).toBeVisible();
  }
  expect(screen.getByText("新增")).toBeVisible();
  expect(screen.getByText("覆盖")).toBeVisible();
  expect(screen.getByText("跳过")).toBeVisible();
  expect(screen.getByText("冲突")).toBeVisible();
});

it("separates workspace deletion from content trash", () => {
  render(<TrashCenter fixture={trashFixture} role="admin" />);
  expect(screen.queryByRole("button", { name: "删除工作区" })).not.toBeInTheDocument();
});

it("keeps Demo read-only and hides paid configuration", () => {
  render(<DemoWorkspace initialWorkspace={demoFixture} />);
  expect(screen.getByText("示例工作区 · 只读")).toBeVisible();
  expect(screen.queryByText("API Key")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /上传/ })).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
pnpm --filter web test:run -- src/components/exports src/components/demo-workspace.test.tsx src/components/operations src/components/risk/risk-knowledge-center.test.tsx
```

- [ ] **Step 3: Implement governance and data pages**

Risk knowledge shows platform on every row, document lifecycle, version chain, chunks/citations, feedback review, rule candidates, and fixed Mock evaluation. Export/backup shows scope, includes, excludes, state, created/expiry time, and safe action. Trash shows recoverability, deadline, evidence hold, and content-only permanent deletion; workspace deletion remains in settings danger zone with the existing two-confirmation flow.

- [ ] **Step 4: Implement settings hierarchy and operation states**

Settings secondary navigation contains:

```ts
export const SETTINGS_ITEMS = [
  "工作区概览",
  "成员与邀请码",
  "平台账号配置",
  "指标、目标与基准",
  "模型配置与预算",
  "保留策略",
  "危险操作",
] as const;
```

Jobs show type, state, stage, safe error code, allowed cancel/retry, compensation, dead-letter equivalent, and PostgreSQL/Redis/S3 readiness. Editor is read-only. Secret inputs never echo values or offer a base URL.

- [ ] **Step 5: Restyle Demo and mobile governance behavior**

Use the same bright panel, typography, status, and spacing primitives. Keep a fixed read-only banner and only the existing bounded Mock generation. On mobile, ZIP restore, model configuration, complex knowledge review, and workspace deletion render `DesktopOnlyNotice`.

- [ ] **Step 6: Run domain, frontend, Demo, and backup E2E checks**

```bash
pnpm --filter web test:run
pnpm --filter web lint
pnpm --filter web typecheck
pnpm --filter web build
cd apps/api
.venv/bin/pytest tests/exports tests/operations tests/risk_rag tests/models tests/workspace -q
cd ../..
pnpm --dir tests/e2e test -- demo.spec.ts backup-restore.spec.ts qianwen-config.spec.ts
```

- [ ] **Step 7: Commit**

```bash
git add apps/web/src/app/workspaces/[workspaceId]/risk-knowledge apps/web/src/app/workspaces/[workspaceId]/data-management apps/web/src/app/workspaces/[workspaceId]/settings apps/web/src/components/exports apps/web/src/components/workspace apps/web/src/components/operations apps/web/src/components/demo-workspace*
git commit -m "feat: unify governance and workspace management"
```

---

### Task 10: Route Acceptance, Visual Regression, and Task 9B Reset

**Files:**
- Create: `tests/e2e/workbench-navigation.spec.ts`
- Create: `tests/e2e/workbench-mobile.spec.ts`
- Create: `tests/e2e/workbench-visual.spec.ts`
- Modify: `tests/e2e/full-loop.spec.ts`
- Modify: `tests/e2e/content-detail.spec.ts`
- Modify: `tests/e2e/public-demo-screenshot.spec.ts`
- Modify: `docs/acceptance/requirements-traceability.md`
- Modify: `docs/acceptance/non-developer-test-guide.md`
- Modify: `docs/acceptance/test-session-template.md`
- Create: `docs/acceptance/evidence/workbench-automated-acceptance-2026-07-29.md`
- Create: `docs/acceptance/workbench-route-inventory.md`

**Interfaces:**
- Consumes every canonical route and shared component from Tasks 1–9.
- Produces automated proof that every formal module is reachable, role-appropriate, scope-safe, responsive, and visually stable.
- Produces refreshed Task 9B instructions; it does not fabricate a non-developer result.

- [ ] **Step 1: Add a route inventory test that fails on missing or hidden modules**

```ts
test("admin reaches every primary module from the sidebar", async ({ page }) => {
  const labels = [
    "工作台总览",
    "账号仪表盘",
    "栏目与活动",
    "内容库",
    "数据导入",
    "分析中心",
    "爆款素材库",
    "账号风格",
    "事实资料",
    "生成中心",
    "发布前检查",
    "风控知识库",
    "导出与备份",
    "回收站",
    "后台任务",
    "工作区设置",
  ];
  for (const label of labels) {
    await expect(page.getByRole("link", { name: label })).toBeVisible();
  }
});
```

Add viewer and Demo matrix cases and assert there is no private formal page reachable only by typing a URL.

- [ ] **Step 2: Add scope, return-state, mobile, and visual tests**

Required assertions:

- all-account overview lacks combined platform metrics;
- account dashboard shows one platform/account;
- content/analysis/preflight drill-down returns with filters, sort, and page;
- desktop sidebar expands/collapses;
- 390px viewport uses a modal drawer;
- unsupported mobile actions explain desktop continuation;
- screenshots exist for overview, account dashboard, content list, all five detail tabs, import preview, analysis queue, all five generation steps, risk knowledge, exports, settings, and mobile overview/detail.

- [ ] **Step 3: Update the full-loop E2E to use canonical navigation**

The flow must navigate visibly through:

```text
工作台 → 账号 → 栏目 → 导入 → 内容 → 分析 → 爆款 → 事实
→ 风格 → 生成五步 → 发布前检查 → 保存草稿 → 导出/恢复
```

No step may jump directly to a hidden route unless that deep-link behavior is the feature under test.

- [ ] **Step 4: Run the complete verification matrix**

```bash
cd apps/api
.venv/bin/pytest -q
.venv/bin/ruff check app tests
.venv/bin/mypy app
cd ../..
pnpm --filter web test:run
pnpm --filter extension test
pnpm --filter web lint
pnpm --filter web typecheck
pnpm --filter web build
pnpm --dir tests/e2e test
git diff --check
```

Also run the repository’s existing OpenAPI drift, platform metric type drift, empty-schema migration, Alembic check, schema consistency, Compose config, secret scan, dependency audit, and SBOM verification commands exactly as defined by CI.

Expected: no Critical/Important review issue; all automated suites pass; visual snapshots contain only synthetic data.

- [ ] **Step 5: Perform specification traceability review**

Update `requirements-traceability.md` so each original AC-01 through AC-16 points to:

- its canonical workbench route;
- its focused component/API test;
- its E2E evidence;
- an honest `passed`, `partial`, or `not_run` status.

Keep real Qianwen, real creator pages, Windows/Edge, and independent non-developer testing as `not_run` unless actually performed. Do not turn Mock or synthetic evidence into production compatibility claims.

- [ ] **Step 6: Prepare, but do not forge, the new Task 9B session**

Revise the participant card for the new navigation. The participant must independently:

1. enter with an editor invite;
2. identify workspace/account/content scope;
3. import the synthetic spreadsheet;
4. inspect analysis;
5. find viral/style/facts;
6. complete a Mock generation;
7. find preflight and export;
8. return to the starting queue without losing context.

Record actual time, errors, requests for help, and participant wording only after the session occurs.

- [ ] **Step 7: Request final code review and commit**

Use `superpowers:requesting-code-review`, resolve every Critical/Important finding with a new RED→GREEN test, rerun Step 4, then:

```bash
git add tests/e2e docs/acceptance
git commit -m "test: accept modular operations workbench"
```

---

## Final Completion Gate

The redesign is complete only when:

1. Tasks 1–10 are committed on `codex/workbench-redesign`.
2. The worktree is clean.
3. Every private formal module is reachable from visible navigation.
4. All-account pages contain no mixed-platform business metrics.
5. Old private deep links resolve to canonical routes safely.
6. API, Web, Extension, E2E, OpenAPI, migration, security, dependency, and supply-chain checks pass.
7. The design specification mapping has no uncovered requirement.
8. Task 9B is rerun with a real independent non-developer and its result is recorded honestly.
9. Only then use `superpowers:finishing-a-development-branch` to decide the local merge into `codex/backup-open-source`; do not push without explicit user authorization.
