import type { CopyMode } from "./experience-preferences";

export const OPERATOR_PAGE_IDS = [
  "overview", "contents", "contentDetail", "imports", "analysis",
  "accounts", "accountDashboard", "columns", "agent", "generation", "preflight",
  "viralLibrary", "styles", "styleProfile", "facts", "exports", "jobs",
  "riskKnowledge", "trash", "settings", "settingsMembers",
  "settingsModels",
] as const;

export type OperatorPageId = (typeof OPERATOR_PAGE_IDS)[number];
export type ModeAwareCopy = {
  simple: string;
  professional: string;
};
export type OperatorPageCopy = {
  title: string;
  purpose: ModeAwareCopy;
  safety?: ModeAwareCopy;
};

export const copyForMode = (copy: ModeAwareCopy, mode: CopyMode): string =>
  copy[mode];

const copy = (simple: string, professional: string): ModeAwareCopy => ({
  simple,
  professional,
});

export const OPERATOR_COPY_CATALOG: Record<OperatorPageId, OperatorPageCopy> = {
  overview: {
    title: "工作台总览",
    purpose: copy("看清各账号目前缺什么数据、有哪些待处理内容，以及现在最值得先做哪一件事。", "按账号分别查看数据完整度、风险和下一步，不混算不同平台的业务指标。"),
  },
  contents: {
    title: "内容库",
    purpose: copy("集中查看每条作品、发布状态、数据、分析和风险结果。", "按平台、账号、栏目和数据状态查找内容；平台数据始终分别展示。"),
  },
  contentDetail: {
    title: "内容详情",
    purpose: copy("在一处查看这条作品的数据、分析、风险和生成记录。", "展示服务端可确认的生命周期、同口径快照、分析版本、风险扫描和安全关联生成记录。"),
  },
  imports: {
    title: "数据导入",
    purpose: copy("把作品和发布后的运营数据录入系统；确认前不会写入正式记录。", "四种方式共享暂存、预览、修正和人工确认边界；确认前不会写入正式内容或快照。"),
  },
  analysis: {
    title: "分析中心",
    purpose: copy("找出还没分析或分析失败的作品，并查看问题和改进建议。", "队列只展示服务端已经确认的分析状态、样本、Evidence 和置信度；不同平台分别筛选。"),
  },
  accounts: {
    title: "账号仪表盘",
    purpose: copy("分账号查看运营状态；抖音和小红书的数据不会混在一起计算。", "抖音与小红书账号分别展示，不进行跨平台指标合计。"),
  },
  accountDashboard: {
    title: "账号表现",
    purpose: copy("只看这个账号的表现变化、目标完成情况和异常内容。", "仅展示单个平台账号、同口径成熟度和满足样本门槛的服务端图表。"),
  },
  columns: {
    title: "栏目与活动",
    purpose: copy("管理账号平时使用的栏目规则，以及活动期间临时使用的规则。", "栏目和活动独立展示账号继承、临时覆盖、有效时间及当前版本。"),
  },
  agent: {
    title: "运营智能体",
    purpose: copy(
      "告诉系统你想解决的运营问题；先看计划，批准后执行，遇到重要写入会再次请你确认。",
      "使用版本化白名单工具、持久化计划与运行状态、成员级确认和用量治理完成受控工作流。",
    ),
    safety: copy(
      "智能体不会替你发布内容或付款，也不会跳过事实和风险检查。",
      "当前工具目录不包含发布、支付或任意网页操作；受保护写入要求发起成员确认。",
    ),
  },
  generation: {
    title: "生成中心",
    purpose: copy("根据已确认的事实、账号风格和参考内容，生成标题、文案和封面。", "范围、事实、风格与参考、生成编辑和发布前复核依次完成；仅恢复不含正文、图片或凭据的安全元数据。"),
  },
  preflight: {
    title: "发布前检查",
    purpose: copy("集中检查准备发布的内容，处理风险、图片文字识别和资料不足问题。", "标题、正文和封面 OCR 的确定性规则与 RAG 辅助判断分开展示；无证据不代表安全通过。"),
    safety: copy("没有查到规则资料不代表内容安全；图片文字识别不准或发现高风险时，必须人工检查，高风险内容不能发布。", "无有效 Evidence 不等于安全通过；OCR 低置信度必须人工复核，RAG 不得降低确定性规则等级，高风险受发布门禁阻断。"),
  },
  viralLibrary: {
    title: "爆款素材库",
    purpose: copy("保存确认过的优秀内容结构，之后生成内容时可以继续参考。", "候选只表示单账号历史范围内的相对表现，人工确认后才成为可复用资产。"),
  },
  styles: {
    title: "账号风格",
    purpose: copy("选择一个账号，查看并维护它常用的标题、文案和封面风格。", "风格档案始终固定到单个平台账号，不提供全部账号合并视图。"),
  },
  styleProfile: {
    title: "账号风格中心",
    purpose: copy("用人工确认的样本稳定账号表达；优秀内容结构不会自动变成账号风格。", "最近内容和爆款只作为候选，只有人工选择并确认的版本才会生效。"),
  },
  facts: {
    title: "事实资料",
    purpose: copy("保存商品、活动或选题中可以确认的事实，生成时用它减少写错和虚假宣传。", "系统只约束生成内容与已确认资料一致，不证明资料本身客观真实。"),
  },
  exports: {
    title: "导出与备份",
    purpose: copy("导出运营数据和分析报告，或备份整个工作区后再恢复。", "所有文件通过异步任务生成；短期下载地址不写入浏览器存储，恢复必须先预览再确认。"),
  },
  jobs: {
    title: "后台任务",
    purpose: copy("查看导入、分析、生成和备份等耗时任务有没有完成，失败后该怎么处理。", "只展示状态、阶段和安全错误码，不展示任务正文、截图或模型响应。"),
  },
  riskKnowledge: {
    title: "风控知识库",
    purpose: copy("管理平台规则资料；只有审核并生效的资料才会用于内容检查。", "文档正文始终是不可信资料；扫描只使用已生效、已到生效日期的对应平台版本。"),
  },
  trash: {
    title: "回收站",
    purpose: copy("恢复还在保留期内的内容；永久删除工作区要到设置中单独操作。", "只展示支持软删除的内容资源；工作区删除使用独立影响预览和二次确认。"),
  },
  settings: {
    title: "工作区设置",
    purpose: copy("管理成员、账号、模型费用限制和工作区安全操作。", "统一展示工作区边界、权限和安全状态；所有变更仍由服务端权限和版本规则决定。"),
  },
  settingsMembers: {
    title: "成员与邀请码",
    purpose: copy("给每个人创建独立邀请码、设置权限，并在成员离开时单独撤销。", "坚持一人一码、一种角色；邀请码只显示一次且不写入 URL 或持久化存储。"),
  },
  settingsModels: {
    title: "模型配置",
    purpose: copy("配置要使用的千问能力和每日费用上限；真实调用前请先确认地域和预算。", "管理固定 Catalog、地域、实验状态、API Key、用量政策和受控真实验收。"),
  },
};
