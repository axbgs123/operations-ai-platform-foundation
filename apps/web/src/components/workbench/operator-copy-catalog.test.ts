import { expect, test } from "vitest";
import { ALL_WORKBENCH_MODULE_LABELS } from "./navigation";
import {
  OPERATOR_COPY_CATALOG,
  OPERATOR_PAGE_IDS,
  copyForMode,
} from "./operator-copy-catalog";
import {
  PAGE_GUIDANCE_CATALOG,
  nextActionForRole,
} from "./page-guidance-catalog";

test("covers the 15 primary modules and retained detail surfaces", () => {
  expect(OPERATOR_PAGE_IDS).toEqual([
    "overview", "contents", "contentDetail", "imports", "analysis",
    "accounts", "accountDashboard", "columns", "agent", "hotspots", "generation", "preflight",
    "viralLibrary", "styles", "styleProfile", "facts", "exports", "jobs",
    "riskKnowledge", "trash", "settings", "settingsMembers",
    "settingsModels",
  ]);
  expect(new Set(ALL_WORKBENCH_MODULE_LABELS)).toHaveLength(15);
  for (const id of OPERATOR_PAGE_IDS) {
    expect(OPERATOR_COPY_CATALOG[id].purpose.simple.length).toBeGreaterThan(12);
    expect(OPERATOR_COPY_CATALOG[id].purpose.professional.length).toBeGreaterThan(12);
    expect(PAGE_GUIDANCE_CATALOG[id].steps.length).toBeGreaterThanOrEqual(3);
  }
});

test("keeps developer terms out of primary easy copy", () => {
  const forbidden = /\b(?:RAG|Mock|Evidence|Worker|Schema|Provider|API)\b|门禁|向量|幂等/i;
  for (const page of Object.values(OPERATOR_COPY_CATALOG)) {
    expect(page.purpose.simple).not.toMatch(forbidden);
  }
});

test("preserves exact professional copy while selecting simple by default", () => {
  const copy = OPERATOR_COPY_CATALOG.analysis.purpose;
  expect(copyForMode(copy, "simple")).toBe(
    "找出还没分析或分析失败的作品，并查看问题和改进建议。",
  );
  expect(copyForMode(copy, "professional")).toBe(
    "队列只展示服务端已经确认的分析状态、样本、Evidence 和置信度；不同平台分别筛选。",
  );
});

test("uses professional maturity wording in account dashboard guidance", () => {
  const step = PAGE_GUIDANCE_CATALOG.accountDashboard.steps[0];
  expect(step.simple).toBe("选择作品类型和数据采集时间。");
  expect(step.professional).toBe(
    "选择作品类型和数据成熟度：1h、24h、72h 或 7d。",
  );
});

test("never gives a viewer a write action", () => {
  for (const entry of Object.values(PAGE_GUIDANCE_CATALOG)) {
    const action = nextActionForRole(entry, "viewer");
    expect(action.kind).not.toBe("write");
  }
});

test("keeps required safety meaning in both modes", () => {
  const risk = OPERATOR_COPY_CATALOG.preflight.safety;
  expect(risk!.simple).toMatch(/不代表安全|人工检查|不能发布/);
  expect(risk!.professional).toMatch(/RAG|OCR|证据|门禁/);
});
