import { expect, test } from "vitest";

import {
  exportBoundaryCopy,
  generationTermCopy,
  internalReferenceCopy,
  importHistoryActionCopy,
  knowledgeTermCopy,
  restoreActionCopy,
  restorePhaseCopy,
  restoreReasonCopy,
  restoreRecordTypeCopy,
  riskAuthorizationStatusCopy,
  riskDocumentStatusCopy,
  riskSourceLevelCopy,
  riskTypeCopy,
  trashResourceCopy,
} from "./operator-display-copy";

test("maps controlled risk categories while preserving exact professional IDs", () => {
  expect(riskTypeCopy("contact_format")).toEqual({
    simple: "联系方式格式风险",
    professional: "contact_format",
  });
  expect(riskTypeCopy("external_contact")).toEqual({
    simple: "站外联系方式风险",
    professional: "external_contact",
  });
  expect(riskTypeCopy("absolute_claim")).toEqual({
    simple: "绝对化宣传风险",
    professional: "absolute_claim",
  });
  expect(riskTypeCopy("unverified_claim")).toEqual({
    simple: "未经确认的宣传风险",
    professional: "unverified_claim",
  });
  expect(riskTypeCopy("price_claim")).toEqual({
    simple: "价格信息风险",
    professional: "price_claim",
  });
  expect(riskTypeCopy("effect_claim")).toEqual({
    simple: "功效宣传风险",
    professional: "effect_claim",
  });
  expect(riskTypeCopy("certification_claim")).toEqual({
    simple: "认证资质风险",
    professional: "certification_claim",
  });
  expect(riskTypeCopy("material_claim")).toEqual({
    simple: "材质描述风险",
    professional: "material_claim",
  });
});

test("keeps unknown risk IDs professional-only and directs easy users to the reason", () => {
  expect(riskTypeCopy("unknown_rule_id")).toEqual({
    simple: "其他风险类型，具体原因见下方说明",
    professional: "unknown_rule_id",
  });
});

test("maps knowledge governance terms without changing professional terminology", () => {
  expect(knowledgeTermCopy("chunk")).toEqual({
    simple: "规则片段",
    professional: "Chunk",
  });
  expect(knowledgeTermCopy("citation")).toEqual({
    simple: "引用检查",
    professional: "Citation",
  });
  expect(knowledgeTermCopy("bundle")).toEqual({
    simple: "本次判断资料",
    professional: "Evidence Bundle",
  });
  expect(knowledgeTermCopy("mock")).toEqual({
    simple: "固定合成评估",
    professional: "Mock",
  });
  expect(knowledgeTermCopy("rag")).toEqual({
    simple: "规则资料辅助判断",
    professional: "RAG",
  });
  expect(knowledgeTermCopy("ocr")).toEqual({
    simple: "图片文字识别",
    professional: "OCR",
  });
});

test("maps export exclusions without weakening the excluded-data boundary", () => {
  expect(exportBoundaryCopy("prompt")).toEqual({
    simple: "生成指令",
    professional: "Prompt",
  });
  expect(exportBoundaryCopy("embedding")).toEqual({
    simple: "资料检索索引",
    professional: "Embedding",
  });
  expect(exportBoundaryCopy("provider_workspace")).toEqual({
    simple: "模型服务私有标识",
    professional: "Provider Workspace ID",
  });
  expect(exportBoundaryCopy("worker_runtime")).toEqual({
    simple: "后台任务运行状态",
    professional: "Worker claim、lease 和 heartbeat",
  });
});

test("maps generation terms and keeps the experimental warning exact", () => {
  expect(generationTermCopy("provider")).toEqual({
    simple: "模型服务",
    professional: "Provider",
  });
  expect(generationTermCopy("gate")).toEqual({
    simple: "检查规则",
    professional: "门禁",
  });
  expect(generationTermCopy("ocr")).toEqual({
    simple: "图片文字识别",
    professional: "OCR",
  });
  expect(generationTermCopy("experimental")).toEqual({
    simple: "试用状态，真实效果和费用尚未完成验收",
    professional: "Provider experimental",
  });
});

test("keeps internal references out of easy mode while preserving professional values", () => {
  expect(internalReferenceCopy("objective-1", "发布时目标配置")).toEqual({
    simple: "发布时目标配置：已记录，可在专业模式查看",
    professional: "objective-1",
  });
  expect(internalReferenceCopy(null, "发布时基准配置")).toEqual({
    simple: "发布时基准配置：当前记录未提供",
    professional: "当前记录未提供",
  });
});

test("maps risk document lifecycle and version metadata without exposing raw easy values", () => {
  expect(riskDocumentStatusCopy("active", 1)).toEqual({
    simple: "当前生效 · 版本已记录，可在专业模式查看",
    professional: "active · v1",
  });
  expect(riskDocumentStatusCopy("pending_review", 2).simple).toBe(
    "等待审核 · 版本已记录，可在专业模式查看",
  );
  expect(riskDocumentStatusCopy("rejected", 3).simple).toBe(
    "已驳回 · 版本已记录，可在专业模式查看",
  );
  expect(riskDocumentStatusCopy("superseded", 4).simple).toBe(
    "已被新版本替代 · 版本已记录，可在专业模式查看",
  );
  expect(riskDocumentStatusCopy("expired", 5).simple).toBe(
    "已失效 · 版本已记录，可在专业模式查看",
  );
  expect(riskDocumentStatusCopy("inactive", 6).simple).toBe(
    "当前未生效 · 版本已记录，可在专业模式查看",
  );
});

test("keeps unknown risk document lifecycle values professional-only", () => {
  expect(riskDocumentStatusCopy("internal_transition", 42)).toEqual({
    simple: "当前状态暂时无法识别 · 版本已记录，可在专业模式查看",
    professional: "internal_transition · v42",
  });
});

test("explains every risk source level while preserving exact professional levels", () => {
  expect(riskSourceLevelCopy("S1")).toEqual({
    simple: "平台官方规则或公告",
    professional: "S1",
  });
  expect(riskSourceLevelCopy("S2")).toEqual({
    simple: "法律法规或监管材料",
    professional: "S2",
  });
  expect(riskSourceLevelCopy("S3")).toEqual({
    simple: "团队真实违规记录（默认私有）",
    professional: "S3",
  });
  expect(riskSourceLevelCopy("S4")).toEqual({
    simple: "已人工审核的行业案例",
    professional: "S4",
  });
  expect(riskSourceLevelCopy("S5")).toEqual({
    simple: "未经验证的用户经验（仅用于低可信提示）",
    professional: "S5",
  });
  expect(riskSourceLevelCopy("internal_source")).toEqual({
    simple: "来源等级已记录，可在专业模式查看",
    professional: "internal_source",
  });
});

test("maps risk authorization meaning without changing the professional state", () => {
  expect(riskAuthorizationStatusCopy("not_required")).toEqual({
    simple: "无需额外授权",
    professional: "not_required",
  });
  expect(riskAuthorizationStatusCopy("authorized")).toEqual({
    simple: "已获得使用授权",
    professional: "authorized",
  });
  expect(riskAuthorizationStatusCopy("unverified")).toEqual({
    simple: "授权尚未确认",
    professional: "unverified",
  });
  expect(riskAuthorizationStatusCopy("restricted")).toEqual({
    simple: "使用受到限制",
    professional: "restricted",
  });
  expect(riskAuthorizationStatusCopy("internal_authorization")).toEqual({
    simple: "授权状态已记录，可在专业模式查看",
    professional: "internal_authorization",
  });
});

test("maps restore phases, actions, record types, and reasons with safe fallbacks", () => {
  expect(restorePhaseCopy("preview_ready")).toEqual({
    simple: "恢复预览已准备，尚未修改正式数据",
    professional: "preview_ready",
  });
  expect(restorePhaseCopy("database")).toEqual({
    simple: "正在恢复结构化记录",
    professional: "database",
  });
  expect(restorePhaseCopy("internal_phase")).toEqual({
    simple: "恢复阶段已记录，可在专业模式查看",
    professional: "internal_phase",
  });
  expect(restoreActionCopy("overwrite")).toEqual({
    simple: "覆盖",
    professional: "overwrite",
  });
  expect(restoreActionCopy("internal_action")).toEqual({
    simple: "恢复动作已记录，可在专业模式查看",
    professional: "internal_action",
  });
  expect(restoreRecordTypeCopy("platform_account")).toEqual({
    simple: "平台账号",
    professional: "platform_account",
  });
  expect(restoreRecordTypeCopy("risk_document_metadata")).toEqual({
    simple: "风险规则资料",
    professional: "risk_document_metadata",
  });
  expect(restoreRecordTypeCopy("internal_record")).toEqual({
    simple: "记录类型已保存，可在专业模式查看",
    professional: "internal_record",
  });
  expect(restoreReasonCopy("safe_mutable_fields_changed")).toEqual({
    simple: "可安全迁移的字段有变化，将覆盖现有记录",
    professional: "safe_mutable_fields_changed",
  });
  expect(restoreReasonCopy("immutable_record_changed")).toEqual({
    simple: "不可变历史记录有变化，已阻断恢复",
    professional: "immutable_record_changed",
  });
  expect(restoreReasonCopy("internal_reason")).toEqual({
    simple: "恢复原因已记录，可在专业模式查看",
    professional: "internal_reason",
  });
});

test("keeps trash identifiers professional-only when no display name exists", () => {
  expect(trashResourceCopy("content", "content-1")).toEqual({
    simple: "已记录，可在专业模式查看",
    professional: "content · content-1",
  });
  expect(trashResourceCopy("content", "content-1", "活动复盘")).toEqual({
    simple: "活动复盘",
    professional: "content · content-1",
  });
});

test("keeps Viewer import review guidance read-only and directs confirmation to an Admin or Editor", () => {
  expect(importHistoryActionCopy("review", "viewer")).toEqual({
    simple: "查看等待确认的导入记录；需要确认时请联系管理员或编辑者。",
    professional: "Viewer 只读查看等待确认的导入记录；继续确认需要 Admin 或 Editor。",
  });
});

test("keeps Viewer import failure guidance read-only and directs retries to an Admin or Editor", () => {
  expect(importHistoryActionCopy("retry", "viewer")).toEqual({
    simple: "查看导入失败原因；需要重试时请联系管理员或编辑者。",
    professional: "Viewer 只读查看导入失败原因；重试需要 Admin 或 Editor。",
  });
});

test("keeps Viewer wait and result history actions as viewing only", () => {
  expect(importHistoryActionCopy("wait", "viewer")).toEqual({
    simple: "查看状态",
    professional: "Viewer 只读查看状态",
  });
  expect(importHistoryActionCopy("open_result", "viewer")).toEqual({
    simple: "查看结果",
    professional: "Viewer 只读查看结果",
  });
});
