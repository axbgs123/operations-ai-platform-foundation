import { expect, test } from "vitest";

import {
  exportBoundaryCopy,
  generationTermCopy,
  internalReferenceCopy,
  knowledgeTermCopy,
  riskTypeCopy,
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
