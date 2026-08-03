import type { CopyMode } from "./experience-preferences";
import type { WorkbenchRole } from "./navigation";
import type { ModeAwareCopy } from "./operator-copy-catalog";

export function displayCopy(
  simple: string,
  professional: string,
): ModeAwareCopy {
  return { simple, professional };
}

export function displayText(copy: ModeAwareCopy, mode: CopyMode): string {
  return copy[mode];
}

function rawState(
  value: string,
  simpleStates: Readonly<Record<string, string>>,
  fallback: string,
): ModeAwareCopy {
  return displayCopy(simpleStates[value] ?? fallback, value);
}

export const OPERATOR_TERMS = {
  maturity: displayCopy("数据采集时间", "数据成熟度"),
  snapshotMaturity: displayCopy("数据采集时间", "快照成熟度"),
  confidence: displayCopy("判断可靠程度", "置信度"),
  evidence: displayCopy("判断资料", "Evidence"),
  ocr: displayCopy("图片文字识别", "OCR"),
  provider: displayCopy("模型服务", "Provider"),
  embedding: displayCopy("资料检索索引", "Embedding"),
  gate: displayCopy("展示条件", "门禁"),
} as const satisfies Record<string, ModeAwareCopy>;

const confidenceStates: Readonly<Record<string, string>> = {
  high: "高",
  medium: "中",
  low: "低",
  unknown: "暂时无法判断",
};

export function analysisConfidenceCopy(value: string): ModeAwareCopy {
  return rawState(value, confidenceStates, "暂时无法判断");
}

export function dashboardConfidenceCopy(value: string): ModeAwareCopy {
  const simple = {
    raw_only: "只有原始数据，暂不判断",
    low_confidence: "当前判断把握较低",
    normal: "判断依据充足",
  }[value] ?? "当前判断依据待检查";
  const professional = {
    raw_only: "仅原始值",
    low_confidence: "低置信度",
    normal: "正常置信度",
  }[value] ?? value;
  return displayCopy(simple, professional);
}

export function taskStatusCopy(value: string): ModeAwareCopy {
  return rawState(value, {
    queued: "等待处理",
    running: "正在处理",
    retrying: "正在安全重试",
    succeeded: "已完成",
    failed: "处理失败",
    cancelled: "已取消",
    compositing: "正在合成图片",
    risk_scanning: "正在检查发布风险",
    provider_calling: "模型服务正在处理",
    validating: "正在检查结果",
    provider_outcome_unknown: "模型服务结果暂时无法确认",
    compensation_required: "自动清理没有完成，需要管理员处理",
    not_run: "尚未运行",
  }, "当前状态暂时无法识别");
}

export function adoptionStatusCopy(value: string | null): ModeAwareCopy {
  if (!value) return displayCopy("当前记录未提供", "当前记录未提供");
  return rawState(value, {
    adopted: "已采用",
    rejected: "未采用",
    pending: "等待决定",
    saved: "已保存",
  }, "当前采用状态暂时无法识别");
}

export function preflightStatusCopy(value: string): ModeAwareCopy {
  const professional = {
    pending_scan: "待扫描",
    high_risk_blocked: "高风险阻断",
    low_confidence_ocr: "OCR低置信度",
    no_active_rag_evidence: "无有效RAG证据",
    modified_awaiting_rescan: "已修改待复检",
    manually_confirmed: "已通过人工确认",
    review_required: "待人工确认",
    scan_failed: "检查失败",
  }[value] ?? value;
  const simple = {
    pending_scan: "待扫描",
    high_risk_blocked: "高风险阻断",
    low_confidence_ocr: "图片文字识别可信度低",
    no_active_rag_evidence: "缺少可用规则资料",
    modified_awaiting_rescan: "已修改待复检",
    manually_confirmed: "已通过人工确认",
    review_required: "待人工确认",
    scan_failed: "检查失败",
  }[value] ?? "当前检查状态暂时无法识别";
  return displayCopy(simple, professional);
}

export function preflightOcrCopy(value: string): ModeAwareCopy {
  return rawState(value, {
    not_run: "尚未检查图片文字",
    succeeded: "图片文字识别已完成",
    low_confidence: "可信度较低，必须人工检查",
    failed: "图片文字识别失败，不能视为安全通过",
    unavailable: "当前没有可用的图片文字识别结果",
  }, "图片文字识别状态暂时无法确认");
}

export function preflightEvidenceCopy(value: string): ModeAwareCopy {
  return rawState(value, {
    available: "已找到可用规则资料",
    no_active_evidence: "没有可用规则资料，不代表内容安全",
    unavailable: "当前无法确认规则资料状态",
  }, "当前无法确认规则资料状态");
}

export function riskSeverityCopy(value: string): ModeAwareCopy {
  return rawState(value, {
    high: "高风险",
    medium: "中风险",
    low: "低风险",
  }, "风险等级暂时无法识别");
}

export function riskDocumentStatusCopy(
  status: string,
  version: number,
): ModeAwareCopy {
  const simpleStatus = {
    draft: "草稿",
    parsed: "已完成解析",
    pending_review: "等待审核",
    active: "当前生效",
    rejected: "已驳回",
    superseded: "已被新版本替代",
    expired: "已失效",
    inactive: "当前未生效",
  }[status] ?? "当前状态暂时无法识别";
  return displayCopy(
    `${simpleStatus} · 版本已记录，可在专业模式查看`,
    `${status} · v${version}`,
  );
}

const riskTypeAliases: Readonly<Record<string, string>> = {
  contact_format: "联系方式格式风险",
  external_contact: "站外联系方式风险",
  absolute_claim: "绝对化宣传风险",
  unverified_claim: "未经确认的宣传风险",
  price_claim: "价格信息风险",
  effect_claim: "功效宣传风险",
  certification_claim: "认证资质风险",
  material_claim: "材质描述风险",
};

export function riskTypeCopy(value: string): ModeAwareCopy {
  return displayCopy(
    riskTypeAliases[value] ?? "其他风险类型，具体原因见下方说明",
    value,
  );
}

export function knowledgeTermCopy(
  value: "chunk" | "citation" | "bundle" | "mock" | "rag" | "ocr",
): ModeAwareCopy {
  return {
    chunk: displayCopy("规则片段", "Chunk"),
    citation: displayCopy("引用检查", "Citation"),
    bundle: displayCopy("本次判断资料", "Evidence Bundle"),
    mock: displayCopy("固定合成评估", "Mock"),
    rag: displayCopy("规则资料辅助判断", "RAG"),
    ocr: displayCopy("图片文字识别", "OCR"),
  }[value];
}

export function exportBoundaryCopy(
  value: "prompt" | "embedding" | "provider_workspace" | "worker_runtime",
): ModeAwareCopy {
  return {
    prompt: displayCopy("生成指令", "Prompt"),
    embedding: displayCopy("资料检索索引", "Embedding"),
    provider_workspace: displayCopy("模型服务私有标识", "Provider Workspace ID"),
    worker_runtime: displayCopy(
      "后台任务运行状态",
      "Worker claim、lease 和 heartbeat",
    ),
  }[value];
}

export function generationTermCopy(
  value: "provider" | "gate" | "ocr" | "experimental",
): ModeAwareCopy {
  return {
    provider: displayCopy("模型服务", "Provider"),
    gate: displayCopy("检查规则", "门禁"),
    ocr: displayCopy("图片文字识别", "OCR"),
    experimental: displayCopy(
      "试用状态，真实效果和费用尚未完成验收",
      "Provider experimental",
    ),
  }[value];
}

export function internalReferenceCopy(
  value: string | null | undefined,
  easyLabel: string,
): ModeAwareCopy {
  if (!value) {
    return displayCopy(
      `${easyLabel}：当前记录未提供`,
      "当前记录未提供",
    );
  }
  return displayCopy(
    `${easyLabel}：已记录，可在专业模式查看`,
    value,
  );
}

export function versionValueCopy(value: string | null | undefined): ModeAwareCopy {
  if (!value) return displayCopy("当前记录未提供", "当前记录未提供");
  return displayCopy("已记录，可在专业模式查看", value);
}

export function riskOriginCopy(value: string): ModeAwareCopy {
  const professional = {
    deterministic: "确定性规则命中",
    rag: "RAG 辅助判断",
    deterministic_and_rag: "确定性规则 + RAG",
  }[value] ?? value;
  const simple = {
    deterministic: "固定规则命中",
    rag: "已保存规则资料辅助判断",
    deterministic_and_rag: "固定规则和已保存资料共同判断",
  }[value] ?? "判断来源暂时无法识别";
  return displayCopy(simple, professional);
}

export function riskRegionCopy(value: string): ModeAwareCopy {
  return rawState(value, {
    title: "标题",
    body: "正文",
    cover: "封面",
  }, "内容中的相关位置");
}

export function riskNodeCopy(value: string): ModeAwareCopy {
  return rawState(value, {
    before_generation: "生成前",
    after_generation: "生成后",
    before_publication: "发布前",
    historical_rescan: "历史内容复检",
  }, "当前检查环节暂时无法识别");
}

export function providerSummaryCopy(
  provider: string,
  modelId: string,
): ModeAwareCopy {
  const simple = provider === "mock"
    ? "模拟体验，不调用真实模型，也不会产生模型费用"
    : "真实模型服务，调用可能产生费用";
  return displayCopy(simple, `${provider} / ${modelId}`);
}

export function modelCapabilityCopy(value: string): ModeAwareCopy {
  return rawState(value, {
    text: "文本生成",
    vision: "图片理解",
    embedding: "资料检索",
    image: "图片生成",
  }, "当前能力暂时无法识别");
}

export function modelChoiceCopy(
  capability: string,
  modelId: string,
): ModeAwareCopy {
  const simple = {
    text: "文本生成模型",
    vision: "图片理解模型",
    embedding: "资料检索模型",
    image: "图片生成模型",
  }[capability] ?? "模型能力";
  return displayCopy(simple, `${modelId} · ${capability}`);
}

export function viewerPreflightActionCopy(professionalAction: string): ModeAwareCopy {
  return displayCopy(
    "查看风险原因和当前检查状态；需要处理时请联系管理员或编辑者。",
    `只读查看风险原因和检查状态；“${professionalAction}”需要 Admin 或 Editor。`,
  );
}

export function overviewActionLabel(
  kind: string,
  serverLabel: string,
  role: WorkbenchRole,
  mode: CopyMode,
): string {
  if (role !== "viewer") return serverLabel;
  const simple = {
    confirm_import: "查看等待确认的导入记录；需要确认时请联系管理员或编辑者。",
    review_preflight: "查看高风险内容和风险原因；需要处理时请联系管理员或编辑者。",
    review_analysis: "查看待分析内容和当前状态；需要处理时请联系管理员或编辑者。",
  }[kind] ?? "查看当前事项；需要处理时请联系管理员或编辑者。";
  const professional = `Viewer 只读查看；“${serverLabel}”需要 Admin 或 Editor。`;
  return mode === "simple" ? simple : professional;
}

export function dashboardActionLabel(
  serverLabel: string,
  role: WorkbenchRole,
  mode: CopyMode,
): string {
  if (role !== "viewer") return serverLabel;
  return mode === "simple"
    ? "查看现有结果；需要继续采集数据或记录实验时，请联系管理员或编辑者。"
    : `Viewer 只读查看；“${serverLabel}”需要 Admin 或 Editor。`;
}

export function factSourceKindCopy(value: string): ModeAwareCopy {
  return rawState(value, {
    text: "人工文字说明",
    link: "链接资料",
    web: "网页资料",
    document: "文档",
    image: "图片",
  }, "当前来源类型暂时无法识别");
}

export function factConflictCopy(value: string): ModeAwareCopy {
  return rawState(value, {
    clear: "没有冲突",
    unresolved: "存在未解决冲突",
    overridden: "已由授权成员处理冲突",
  }, "冲突状态暂时无法识别");
}

export function importMethodLabelCopy(value: string): ModeAwareCopy {
  const simple = {
    manual: "手动录入",
    tabular: "Excel / CSV",
    screenshot: "截图识别",
    extension: "浏览器采集",
  }[value] ?? "导入方式";
  const professional = {
    manual: "手动录入",
    tabular: "Excel / CSV",
    screenshot: "截图识别",
    extension: "Capture Extension",
  }[value] ?? value;
  return displayCopy(simple, professional);
}

export function importMethodDescriptionCopy(value: string): ModeAwareCopy {
  const simple = {
    manual: "逐条录入内容和可用的初始指标，先预览再确认。",
    tabular: "设置字段对应关系，检查逐行错误和重复内容后批量确认。",
    screenshot: "识别截图中的文字和数字；可信度较低时必须人工修正。",
    extension: "读取浏览器暂存任务；正式写入仍需回到网页确认。",
  }[value] ?? "选择后查看导入说明。";
  const professional = {
    manual: "逐条录入内容和可用的初始指标，先预览再确认。",
    tabular: "字段映射、逐行错误、重复判断和批量确认。",
    screenshot: "Mock 或受控视觉识别，低置信度必须人工修正。",
    extension: "读取扩展暂存任务，正式写入只能在 Web 中确认。",
  }[value] ?? value;
  return displayCopy(simple, professional);
}

export function importHistoryActionCopy(
  value: string,
  role: WorkbenchRole,
): ModeAwareCopy {
  const professionalAction = {
    wait: "查看状态",
    open_result: "查看结果",
    retry: "查看失败",
    review: "继续确认",
  }[value] ?? "查看下一步";
  if (role !== "viewer") {
    return displayCopy(professionalAction, professionalAction);
  }
  if (value === "review") {
    return displayCopy(
      "查看等待确认的导入记录；需要确认时请联系管理员或编辑者。",
      "Viewer 只读查看等待确认的导入记录；继续确认需要 Admin 或 Editor。",
    );
  }
  if (value === "retry") {
    return displayCopy(
      "查看导入失败原因；需要重试时请联系管理员或编辑者。",
      "Viewer 只读查看导入失败原因；重试需要 Admin 或 Editor。",
    );
  }
  return displayCopy(professionalAction, `Viewer 只读${professionalAction}`);
}
