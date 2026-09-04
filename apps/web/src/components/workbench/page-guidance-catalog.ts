import type { WorkbenchRole } from "./navigation";
import type { ModeAwareCopy, OperatorPageId } from "./operator-copy-catalog";

export type GuidanceAction = {
  kind: "read" | "write" | "contact";
  label: ModeAwareCopy;
};
export type PageGuidanceEntry = {
  nextByRole: Record<WorkbenchRole, GuidanceAction>;
  steps: readonly ModeAwareCopy[];
  concepts: readonly ModeAwareCopy[];
  blockers: readonly ModeAwareCopy[];
};

export function nextActionForRole(
  entry: PageGuidanceEntry,
  role: WorkbenchRole,
): GuidanceAction {
  return entry.nextByRole[role];
}

const sharedConcepts = {
  maturity: {
    simple: "数据采集时间：这份数据是在作品发布后多久记录的。",
    professional: "数据成熟度：1h、24h、72h 或 7d。",
  },
  benchmark: {
    simple: "同类作品比较：和这个账号最近的同类作品比较。",
    professional: "动态基准：按平台、账号、内容类型和成熟度生成。",
  },
  confidence: {
    simple: "判断可靠程度：表示当前结论有多大把握。",
    professional: "置信度：由服务端分析合同返回。",
  },
  staged: {
    simple: "检查后再导入：预览和修改不会直接写进正式数据。",
    professional: "暂存预览：人工确认前不写正式内容或快照。",
  },
} as const satisfies Record<string, ModeAwareCopy>;

const same = (text: string): ModeAwareCopy => ({ simple: text, professional: text });
const action = (kind: GuidanceAction["kind"], label: string): GuidanceAction => ({
  kind,
  label: same(label),
});
const steps = (
  ...items: readonly (string | ModeAwareCopy)[]
): readonly ModeAwareCopy[] =>
  items.map((item) => (typeof item === "string" ? same(item) : item));
const contactBlocker = (blocker: string): ModeAwareCopy =>
  same(`${blocker}当前是查看权限；需要修改时请联系管理员或编辑者。`);
const guidance = (
  admin: GuidanceAction,
  editor: GuidanceAction,
  viewer: GuidanceAction,
  pageSteps: readonly (string | ModeAwareCopy)[],
  blocker: string,
  concepts: readonly ModeAwareCopy[] = [],
): PageGuidanceEntry => ({
  nextByRole: { admin, editor, viewer },
  steps: steps(...pageSteps),
  concepts,
  blockers: [viewer.kind === "contact" ? contactBlocker(blocker) : same(blocker)],
});

export const PAGE_GUIDANCE_CATALOG: Record<OperatorPageId, PageGuidanceEntry> = {
  overview: guidance(
    action("write", "处理系统列出的最高优先级事项"), action("write", "处理系统列出的最高优先级事项"), action("read", "查看账号状态和待分析内容"),
    ["先看“数据状态”，确认哪些账号缺少发布后的数据。", "再看“待处理问题”，确认有没有待分析、风险或失败任务。", "按“下一步行动”只处理当前优先级最高的一项。"],
    "还没有账号时，请先到工作区设置创建抖音或小红书账号。", [sharedConcepts.maturity],
  ),
  contents: guidance(
    action("write", "新建内容或导入作品数据"), action("write", "新建内容或导入作品数据"), action("read", "筛选并打开一条内容"),
    ["选择平台和账号，再按栏目、状态或关键词筛选。", "打开一条作品，查看数据、分析、风险和生成记录。", "需要新增时创建内容，已有作品则导入发布后的数据。"],
    "当前筛选没有作品；调整筛选，或由管理员/编辑者新建内容。", [sharedConcepts.maturity],
  ),
  contentDetail: guidance(
    action("write", "补充数据或处理风险"), action("write", "补充数据或处理风险"), action("read", "查看数据、分析和风险标签"),
    ["在“概览”确认作品和发布状态。", "在“数据快照、分析、风控”查看结果和缺失项。", "有权限时补充数据、重新分析或重新检查风险。"],
    "还没有确认过的数据；先导入并确认一次发布后的表现数据。", [sharedConcepts.maturity, sharedConcepts.confidence],
  ),
  imports: guidance(
    action("write", "选择一种方式导入并检查预览"), action("write", "选择一种方式导入并检查预览"), action("read", "查看最近导入记录"),
    ["选择手动、表格、截图或浏览器扩展。", "在预览中核对平台、账号、标题和运营数据。", "修改错误后确认，系统才会写入正式记录。"],
    "没有选择匹配的平台和账号时，数据不能正式导入。", [sharedConcepts.staged],
  ),
  analysis: guidance(
    action("write", "选择一个平台并处理待分析内容"), action("write", "选择一个平台并处理待分析内容"), action("read", "筛选并查看已有分析结果"),
    ["先选择抖音或小红书，必要时再选账号。", "筛选待分析、进行中、成功或失败状态。", "打开作品查看问题和建议，有权限时重新分析。"],
    "还没有确认过的数据；先导入并确认一次发布后的表现数据。", [sharedConcepts.confidence],
  ),
  accounts: guidance(
    action("write", "配置账号或打开单账号表现"), action("read", "打开一个账号查看表现"), action("read", "打开一个账号查看表现"),
    ["先查看每个账号的数据完整度和待处理数量。", "打开一个账号，避免把不同平台的数据混在一起。", "根据账号页面提示补数据或处理异常内容。"],
    "还没有账号时，请先到工作区设置创建抖音或小红书账号。", [sharedConcepts.maturity],
  ),
  accountDashboard: guidance(
    action("write", "检查缺少的数据并处理异常内容"), action("write", "检查缺少的数据并处理异常内容"), action("read", "查看趋势、目标和异常说明"),
    [
      {
        simple: "选择作品类型和数据采集时间。",
        professional: "选择作品类型和数据成熟度：1h、24h、72h 或 7d。",
      },
      "查看目标、变化趋势、漏斗和异常候选。",
      "根据“下一步行动”补数据或打开异常作品。",
    ],
    "还没有确认过的数据；先导入并确认一次发布后的表现数据。", [sharedConcepts.maturity, sharedConcepts.benchmark],
  ),
  columns: guidance(
    action("write", "新建或调整栏目规则"), action("write", "新建或调整栏目规则"), action("read", "查看当前生效规则"),
    ["选择一个平台账号。", "查看账号默认规则和活动期间的临时规则。", "修改后确认生效时间，并检查何时恢复默认。"],
    "当前账号没有栏目时，可以继续使用账号默认规则。",
    steps(
      "账号默认规则：栏目没有临时设置时使用的规则。",
      "活动临时规则：只在设定的有效时间内覆盖账号默认。",
      "恢复关系：临时规则结束后自动恢复账号默认。",
    ),
  ),
  agent: guidance(
    action("write", "说明目标并检查处理计划"),
    action("write", "说明目标并检查处理计划"),
    action("read", "查看计划、进度和安全结果"),
    [
      "先选择一个平台账号，并说明这次想解决的运营问题。",
      "检查系统列出的步骤，确认无误后再批准执行。",
      "查看执行进度；遇到重要写入时，由发起人确认后继续。",
    ],
    "数据、模型或权限准备不足时，系统会停止并说明下一步，不会猜测执行。",
    steps(
      "处理计划：开始前可检查的步骤清单。",
      "执行进度：保存在服务器中的真实状态，关闭页面后仍可恢复。",
      "需要你确认：可能写入正式记录的步骤会暂停等待决定。",
    ),
  ),
  hotspots: guidance(
    action("write", "选择热点创作，或查看对标账号和评论需求"),
    action("write", "选择热点创作，或查看对标账号和评论需求"),
    action("read", "查看已有热点、对标数据和运营简报"),
    [
      "热点截图创作：确认热点后，让文字模型联网核实并生成带来源的草稿。",
      "对标账号监测：每天读取近期公开作品，找出互动明显突出的内容。",
      "评论与日报：归纳公开评论需求，把自己的数据和对标变化汇总成简报。",
    ],
    "热点生成需要已验证的联网模型；对标和评论采集需要管理员先连接 TikHub。",
    steps(
      "已确认热点：人工检查过的截图识别结果。",
      "对标预警：只和同一账号近期作品比较，不把不同平台数据直接相加。",
      "评论需求：公开评论的规则归类结果，仍需运营人员结合语境判断。",
    ),
  ),
  generation: guidance(
    action("write", "选择平台、账号和栏目后开始生成"), action("write", "选择平台、账号和栏目后开始生成"), action("read", "查看已保存的生成结果"),
    ["先选择平台、账号、栏目和生成目标。", "核对事实，选择是否沿用账号风格和优秀内容参考。", "生成并编辑后，再完成事实和发布风险检查。"],
    "还没有完成模型和费用配置时，请联系管理员；未确认事实不能直接写进确定性文案。",
  ),
  preflight: guidance(
    action("write", "处理高风险和需要人工检查的内容"), action("write", "处理高风险和需要人工检查的内容"), action("read", "查看风险原因和判断依据"),
    ["选择平台和账号，筛选需要处理的状态。", "打开一条内容，核对标题、正文和封面文字风险。", "修改内容后重新检查，直到没有阻断问题。"],
    "暂时没有可用的平台规则资料不代表内容安全；图片文字识别不准时必须人工检查。", [sharedConcepts.confidence],
  ),
  viralLibrary: guidance(
    action("write", "确认一个候选为可复用参考"), action("write", "确认一个候选为可复用参考"), action("read", "查看已确认的优秀内容结构"),
    ["选择单个平台账号。", "比较候选表现和系统给出的参考原因。", "人工确认后，这条内容才能在生成时被引用。"],
    "候选没有经过人工确认时，生成内容不能引用它。", [sharedConcepts.benchmark],
  ),
  styles: guidance(
    action("read", "选择一个账号进入风格中心"), action("read", "选择一个账号进入风格中心"), action("read", "选择一个账号查看风格"),
    ["选择一个平台账号进入风格中心。", "查看该账号是否已有生效风格和历史版本。", "需要修改时选择样本、提取并确认新版本。"],
    "没有人工选择并确认的样本时，系统不会自动生成生效风格。",
  ),
  styleProfile: guidance(
    action("write", "选择样本并确认新版本"), action("write", "选择样本并确认新版本"), action("read", "查看当前生效风格和历史版本"),
    ["选择能代表账号的已发布内容作为样本。", "分别检查标题、文案、封面和禁止项。", "确认新版本后，后续生成才会默认沿用。"],
    "没有人工选择并确认的样本时，系统不会自动生成生效风格。",
  ),
  facts: guidance(
    action("write", "添加来源并确认可用于生成的事实"), action("write", "添加来源并确认可用于生成的事实"), action("read", "查看已确认事实和冲突说明"),
    ["添加网页来源或查看已有来源。", "把可确认的信息整理成事实，并处理冲突。", "只有已确认且没有冲突的事实才能稳定用于生成。"],
    "视觉判断不能证明面料、价格、功效或认证；冲突事实不能用于确定性生成。",
  ),
  exports: guidance(
    action("write", "创建需要的导出文件"), action("write", "创建需要的导出文件"), action("contact", "联系管理员或编辑者创建文件"),
    ["选择 CSV、单条分析报告或 JSON。", "创建任务并等待文件生成。", "生成后在任务历史中下载文件。"],
    "下载地址只在短时间内有效；过期后可重新获取，不需要重复生成文件。", [sharedConcepts.staged],
  ),
  jobs: guidance(
    action("write", "检查失败任务并按安全建议处理"), action("contact", "查看失败任务并联系管理员处理"), action("contact", "联系管理员或编辑者查看后台任务"),
    ["按任务类型和状态筛选。", "查看失败发生在哪个阶段以及建议的处理方式。", "管理员可取消或安全重试；其他角色联系管理员。"],
    "多次尝试仍失败或自动清理未完成时，需要管理员处理。",
  ),
  riskKnowledge: guidance(
    action("write", "审核待处理的平台规则资料"), action("contact", "联系管理员审核或更新规则资料"), action("contact", "联系管理员查看风控资料"),
    ["选择抖音或小红书，平台资料不能混用。", "查看资料版本、来源等级和当前审核状态。", "管理员审核并生效后，资料才会用于检查。"],
    "资料没有审核并生效时，不会参与内容风险判断。",
  ),
  trash: guidance(
    action("write", "恢复仍在保留期内的内容"), action("write", "恢复仍在保留期内的内容"), action("contact", "联系管理员或编辑者恢复内容"),
    ["查看仍在保留期内的已删除内容。", "核对内容、删除时间和是否允许恢复。", "有权限时恢复；永久删除工作区请前往设置。"],
    "超过保留期或因审计要求被保留的内容，不能按普通恢复/删除处理。",
  ),
  settings: guidance(
    action("write", "管理成员、账号和模型连接"), action("contact", "联系管理员修改工作区设置"), action("contact", "联系管理员修改工作区设置"),
    ["查看团队和当前权限。", "管理成员与平台账号。", "需要 AI 功能时连接自己的模型。"],
    "当前角色没有设置权限时，请联系管理员。",
  ),
  settingsMembers: guidance(
    action("write", "创建独立邀请码或检查成员权限"), action("contact", "联系管理员管理成员和邀请码"), action("contact", "联系管理员管理成员和邀请码"),
    ["为新成员选择管理员、编辑者或查看者。", "创建独立邀请码并立即安全交给本人。", "成员离开时单独撤销，不影响其他成员。"],
    "邀请码创建后只显示一次；丢失后只能撤销并重新创建。",
  ),
  settingsModels: guidance(
    action("write", "连接模型并测试是否可用"), action("contact", "联系管理员连接 AI 模型"), action("contact", "联系管理员连接 AI 模型"),
    ["选择千问官方服务，或填写团队自有文本模型的服务信息。", "输入并保存自己的模型密钥。", "进行一次不发送生成内容的连接测试。"],
    "连接测试不发送运营内容；自带模型的费用由对应供应商结算，平台不会猜测价格。",
  ),
};
