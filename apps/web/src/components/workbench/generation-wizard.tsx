"use client";

import Link from "next/link";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactElement,
  type ReactNode,
} from "react";

import { CoverEditor } from "@/components/generation/cover-editor/cover-editor";
import { RiskReport } from "@/components/risk/risk-report";
import { DesktopOnlyNotice, PageHeader, StatusBadge } from "@/components/workbench/ui";
import {
  TextEditor,
  type TextGenerationDraft,
} from "@/app/workspaces/[workspaceId]/generation/text-editor";
import type { FactContextData, FactSourceData } from "@/lib/fact-api";
import type {
  ModelConfig,
  ModelUsagePolicy,
  ModelUsageSummary,
} from "@/lib/model-api";
import type { RiskScanData } from "@/lib/risk-api";
import type { StyleProfileData, StyleScopeData } from "@/lib/style-api";
import type { ViralLibraryItemData } from "@/lib/viral-api";
import type { WorkbenchAccount } from "@/components/workbench/scope-query";
import { editTextGeneration } from "@/lib/generation-api";


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

export type GenerationWizardFixture = {
  accounts: WorkbenchAccount[];
  columns: Array<
    Pick<StyleScopeData, "id" | "name" | "kind" | "starts_at" | "ends_at">
    & {
      account_id?: string;
      workspace_id?: string;
      configuration_override?: Record<string, unknown>;
      created_at?: string;
    }
  >;
  models: ModelConfig[];
  modelUsagePolicies?: ModelUsagePolicy[];
  modelUsageSummary?: ModelUsageSummary | null;
  factSources: FactSourceData[];
  factContext: FactContextData;
  styles: StyleProfileData[];
  viralItems: Array<
    Pick<
      ViralLibraryItemData,
      | "id"
      | "account_id"
      | "content_id"
      | "category"
      | "title"
      | "strategy_tags"
      | "applicable_scenarios"
      | "structure_summary"
      | "active"
      | "generation_eligible"
    >
    & {
      candidate_id?: string;
      platform?: "douyin" | "xiaohongshu";
      confirmed_by?: string | null;
      confirmed_at?: string;
      revoked_at?: string | null;
      revocation_reason?: string | null;
    }
  >;
  riskScan: RiskScanData | null;
};

const steps: { id: GenerationStep; label: string }[] = [
  { id: "scope", label: "范围与目标" },
  { id: "facts", label: "事实资料" },
  { id: "references", label: "风格与参考" },
  { id: "generate", label: "生成与编辑" },
  { id: "review", label: "复核与保存" },
];
const stepIds = new Set(steps.map((step) => step.id));

export function normalizeGenerationStep(value: string | null): GenerationStep {
  return value && stepIds.has(value as GenerationStep)
    ? value as GenerationStep
    : "scope";
}

export function generationDraftStorageKey(
  workspaceId: string,
  memberId: string,
): string {
  return `operations-ai:generation-draft:${workspaceId}:${memberId}`;
}

export function serializeSafeGenerationDraft(
  draft: GenerationWizardState,
): string {
  return JSON.stringify({
    step: normalizeGenerationStep(draft.step),
    accountId: draft.accountId,
    columnId: draft.columnId,
    objectiveId: draft.objectiveId,
    inheritTitleStyle: draft.inheritTitleStyle,
    inheritCopyStyle: draft.inheritCopyStyle,
    inheritCoverStyle: draft.inheritCoverStyle,
    viralReferenceIds: draft.viralReferenceIds.slice(0, 3),
    factSourceIds: draft.factSourceIds,
  });
}

function readSafeGenerationDraft(
  workspaceId: string,
  memberId: string | undefined,
): Partial<GenerationWizardState> {
  if (!memberId || typeof sessionStorage === "undefined") return {};
  const raw = sessionStorage.getItem(
    generationDraftStorageKey(workspaceId, memberId),
  );
  if (!raw || raw.length > 20_000) return {};
  try {
    const candidate = JSON.parse(raw) as Record<string, unknown>;
    const stringOrNull = (value: unknown) =>
      typeof value === "string" ? value : value === null ? null : undefined;
    const strings = (value: unknown) =>
      Array.isArray(value)
        ? value.filter((item): item is string => typeof item === "string").slice(0, 100)
        : undefined;
    return {
      step: normalizeGenerationStep(
        typeof candidate.step === "string" ? candidate.step : null,
      ),
      accountId: stringOrNull(candidate.accountId),
      columnId: stringOrNull(candidate.columnId),
      objectiveId: stringOrNull(candidate.objectiveId),
      inheritTitleStyle:
        typeof candidate.inheritTitleStyle === "boolean"
          ? candidate.inheritTitleStyle
          : undefined,
      inheritCopyStyle:
        typeof candidate.inheritCopyStyle === "boolean"
          ? candidate.inheritCopyStyle
          : undefined,
      inheritCoverStyle:
        typeof candidate.inheritCoverStyle === "boolean"
          ? candidate.inheritCoverStyle
          : undefined,
      viralReferenceIds: strings(candidate.viralReferenceIds),
      factSourceIds: strings(candidate.factSourceIds),
    };
  } catch {
    return {};
  }
}

function nextStep(current: GenerationStep): GenerationStep {
  const index = steps.findIndex((step) => step.id === current);
  return steps[Math.min(index + 1, steps.length - 1)].id;
}

function previousStep(current: GenerationStep): GenerationStep {
  const index = steps.findIndex((step) => step.id === current);
  return steps[Math.max(index - 1, 0)].id;
}

function selectedFactSources(
  fixture: GenerationWizardFixture,
  state: GenerationWizardState,
): FactSourceData[] {
  return fixture.factSources.filter((source) =>
    state.factSourceIds.includes(source.id)
  );
}

function hasBlockingFactConflict(
  fixture: GenerationWizardFixture,
  state: GenerationWizardState,
): boolean {
  return selectedFactSources(fixture, state).some((source) =>
    source.items.some((item) => item.conflict_status === "unresolved")
  );
}

export function GenerationWizard({
  fixture,
  initialAccountId,
  initialPlatform,
  initialStep,
  memberId,
  onPlatformChange,
  onStateChange,
  onStepChange,
  role,
  sourceManager,
  workspaceId,
}: {
  fixture: GenerationWizardFixture;
  initialAccountId?: string | null;
  initialPlatform?: "douyin" | "xiaohongshu" | null;
  initialStep: GenerationStep | string;
  memberId?: string;
  onPlatformChange?: (platform: "douyin" | "xiaohongshu" | null) => void;
  onStateChange?: (state: GenerationWizardState) => void;
  onStepChange?: (step: GenerationStep) => void;
  role: "admin" | "editor" | "viewer";
  sourceManager?: ReactNode;
  workspaceId: string;
}): ReactElement {
  const canWrite = role !== "viewer";
  const initialAccount = fixture.accounts.find(
    (account) => account.account_id === initialAccountId,
  );
  const [platform, setPlatform] = useState<"douyin" | "xiaohongshu" | null>(
    initialAccount?.platform ?? initialPlatform ?? null,
  );
  const [state, setState] = useState<GenerationWizardState>(() => {
    const stored = readSafeGenerationDraft(workspaceId, memberId);
    const storedAccount = fixture.accounts.find(
      (account) => account.account_id === stored.accountId,
    );
    const accountId = initialAccount?.account_id
      ?? storedAccount?.account_id
      ?? null;
    return {
      step: normalizeGenerationStep(initialStep),
      accountId,
      columnId: fixture.columns.some(
        (column) =>
          column.id === stored.columnId
          && (!column.account_id || column.account_id === accountId),
      )
        ? stored.columnId ?? null
        : null,
      objectiveId: stored.objectiveId ?? null,
      inheritTitleStyle: stored.inheritTitleStyle ?? true,
      inheritCopyStyle: stored.inheritCopyStyle ?? true,
      inheritCoverStyle: stored.inheritCoverStyle ?? true,
      viralReferenceIds: (stored.viralReferenceIds ?? [])
        .filter((id) => fixture.viralItems.some((item) => item.id === id))
        .slice(0, 3),
      factSourceIds: (stored.factSourceIds ?? [])
        .filter((id) => fixture.factSources.some((source) => source.id === id)),
    };
  });
  const [generationDraft, setGenerationDraft] = useState<TextGenerationDraft>({
    run: null,
    finalTitle: "",
    finalCopy: "",
  });
  const [reviewBusy, setReviewBusy] = useState(false);
  const [reviewMessage, setReviewMessage] = useState("");
  const [reviewError, setReviewError] = useState("");
  const stateRef = useRef(state);
  const urlControlled = Boolean(onStepChange);
  const activeStep = urlControlled
    ? normalizeGenerationStep(initialStep)
    : state.step;
  const controlledAccountId = urlControlled
    ? initialAccountId ?? null
    : state.accountId;
  const controlledPlatform = urlControlled
    ? initialPlatform ?? null
    : platform;
  const controlledScopeRef = useRef({
    accountId: controlledAccountId,
    platform: controlledPlatform,
  });

  function update(change: Partial<GenerationWizardState>) {
    const current = urlControlled
      ? {
          ...stateRef.current,
          accountId: controlledAccountId,
          step: activeStep,
        }
      : stateRef.current;
    const next = { ...current, ...change };
    stateRef.current = next;
    setState(next);
    if (memberId) {
      sessionStorage.setItem(
        generationDraftStorageKey(workspaceId, memberId),
        serializeSafeGenerationDraft(next),
      );
    }
    onStateChange?.(next);
  }

  function chooseStep(step: GenerationStep) {
    update({ step });
    onStepChange?.(step);
  }

  useEffect(() => {
    if (!memberId) return;
    sessionStorage.setItem(
      generationDraftStorageKey(workspaceId, memberId),
      serializeSafeGenerationDraft(state),
    );
  }, [memberId, state, workspaceId]);

  useEffect(() => {
    if (!urlControlled) return;
    const previous = controlledScopeRef.current;
    if (
      previous.accountId === controlledAccountId
      && previous.platform === controlledPlatform
    ) {
      return;
    }
    controlledScopeRef.current = {
      accountId: controlledAccountId,
      platform: controlledPlatform,
    };
    const next = {
      ...stateRef.current,
      accountId: controlledAccountId,
      columnId: null,
      factSourceIds: [],
      viralReferenceIds: [],
    };
    stateRef.current = next;
    setState(next);
    if (memberId) {
      sessionStorage.setItem(
        generationDraftStorageKey(workspaceId, memberId),
        serializeSafeGenerationDraft(next),
      );
    }
  }, [
    controlledAccountId,
    controlledPlatform,
    memberId,
    urlControlled,
    workspaceId,
  ]);

  const selectedAccount = fixture.accounts.find(
    (account) => account.account_id === controlledAccountId,
  );
  const visibleColumns = fixture.columns.filter(
    (column) => !column.account_id || column.account_id === controlledAccountId,
  );
  const visibleAccounts = fixture.accounts.filter(
    (account) => !controlledPlatform || account.platform === controlledPlatform,
  );
  const confirmedStyle = useMemo(
    () => fixture.styles.find((style) =>
      style.status === "confirmed"
      && style.account_id === (
        controlledAccountId ?? fixture.styles[0]?.account_id
      )
    ) ?? fixture.styles.find((style) => style.status === "confirmed"),
    [controlledAccountId, fixture.styles],
  );
  const textModel = fixture.models.find((model) => model.capability === "text");
  const factConflict = hasBlockingFactConflict(fixture, state);
  const chosenFacts = selectedFactSources(fixture, state);
  const generationReady = Boolean(
    controlledAccountId
    && state.objectiveId
    && textModel
    && !factConflict,
  );

  async function saveReviewedDraft(
    adoptionStatus: "adopted" | "rejected",
  ) {
    if (!generationDraft.run) return;
    setReviewBusy(true);
    setReviewError("");
    setReviewMessage("");
    try {
      const updated = await editTextGeneration(
        workspaceId,
        generationDraft.run.id,
        {
          final_title: generationDraft.finalTitle,
          final_copy: generationDraft.finalCopy,
          adoption_status: adoptionStatus,
        },
        sessionStorage.getItem("workspace_csrf") ?? "",
      );
      setGenerationDraft((current) => ({ ...current, run: updated }));
      setReviewMessage(
        adoptionStatus === "adopted"
          ? "服务端复检完成，草稿已保存"
          : "本稿已记录为拒绝采用",
      );
    } catch (caught) {
      setReviewError(
        caught instanceof Error ? caught.message : "复检与保存失败",
      );
    } finally {
      setReviewBusy(false);
    }
  }

  const stepPanel = (() => {
    if (activeStep === "scope") {
      return (
        <section className="grid gap-4 rounded-xl border bg-white p-5 sm:grid-cols-2">
          <label className="text-sm font-medium">
            平台
            <select
              aria-label="平台"
              className="mt-1 min-h-11 w-full rounded-lg border bg-white px-3"
              onChange={(event) => {
                const nextPlatform = event.target.value
                  ? event.target.value as "douyin" | "xiaohongshu"
                  : null;
                const compatible = fixture.accounts.find(
                  (account) =>
                    account.account_id === controlledAccountId
                    && account.platform === nextPlatform,
                );
                setPlatform(nextPlatform);
                update({
                  accountId: compatible?.account_id ?? null,
                  columnId: null,
                  factSourceIds: [],
                  viralReferenceIds: [],
                });
                onPlatformChange?.(nextPlatform);
              }}
              value={controlledPlatform ?? ""}
            >
              <option value="">请选择平台</option>
              <option value="douyin">抖音</option>
              <option value="xiaohongshu">小红书</option>
            </select>
          </label>
          <label className="text-sm font-medium">
            账号
            <select
              aria-label="账号"
              className="mt-1 min-h-11 w-full rounded-lg border bg-white px-3"
              onChange={(event) => update({
                accountId: event.target.value || null,
                columnId: null,
                factSourceIds: [],
                viralReferenceIds: [],
              })}
              value={controlledAccountId ?? ""}
            >
              <option value="">请选择账号</option>
              {visibleAccounts.map((account) => (
                <option key={account.account_id} value={account.account_id}>
                  {account.platform === "douyin" ? "抖音" : "小红书"} ·{" "}
                  {account.name}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm font-medium">
            栏目/活动
            <select
              aria-label="栏目/活动"
              className="mt-1 min-h-11 w-full rounded-lg border bg-white px-3"
              disabled={!controlledAccountId}
              onChange={(event) => update({
                columnId: event.target.value || null,
              })}
              value={state.columnId ?? ""}
            >
              <option value="">账号默认</option>
              {visibleColumns.map((column) => (
                <option key={column.id} value={column.id}>{column.name}</option>
              ))}
            </select>
          </label>
          <label className="text-sm font-medium">
            生成目标
            <input
              aria-label="生成目标"
              className="mt-1 min-h-11 w-full rounded-lg border px-3"
              onChange={(event) => update({
                objectiveId: event.target.value || null,
              })}
              placeholder="例如：新品发布、涨粉或转化"
              value={state.objectiveId ?? ""}
            />
          </label>
          <div className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-950 sm:col-span-2">
            <p>
              当前生效配置：由服务端按账号与栏目版本确定；当前只读合同未提供完整配置版本时不在前端猜测。
            </p>
            <p className="mt-1">
              Provider：{textModel
                ? `${textModel.provider} / ${textModel.model_id} / ${textModel.contract_version}`
                : "文本模型未配置"}
              {textModel?.experimental ? "（experimental，未完成真实生产兼容承诺）" : ""}
            </p>
          </div>
        </section>
      );
    }

    if (activeStep === "facts") {
      return (
        <section className="space-y-4 rounded-xl border bg-white p-5">
          <div>
            <h2 className="text-lg font-semibold">事实资料约束</h2>
            <p className="mt-1 text-sm text-[var(--text-secondary)]">
              只会把已选择来源中、服务端已确认且无冲突的事实发送给生成合同。
            </p>
          </div>
          {fixture.factSources.length ? (
            <ul className="space-y-3">
              {fixture.factSources.map((source) => (
                <li className="rounded-lg border p-3" key={source.id}>
                  <p className="font-medium">{source.title} · {source.level}</p>
                  {source.items.map((item) => (
                    <label className="mt-2 flex gap-2 text-sm" key={item.id}>
                      <input
                        aria-label={`${item.field_name} ${item.value}`}
                        checked={state.factSourceIds.includes(source.id)}
                        disabled={item.status !== "confirmed"}
                        onChange={(event) => update({
                          factSourceIds: event.target.checked
                            ? [...new Set([...state.factSourceIds, source.id])]
                            : state.factSourceIds.filter((id) => id !== source.id),
                        })}
                        type="checkbox"
                      />
                      <span>
                        {item.field_name}：{item.value} ·{" "}
                        {item.status === "confirmed" ? "用户已确认" : "尚未确认"}
                      </span>
                    </label>
                  ))}
                  {source.level === "L5" ? (
                    <p className="mt-2 text-sm text-amber-900">
                      L5 视觉推断只能作为候选；面料、成分、价格、尺码、功效、认证、产地和安全承诺不能据此进入确定性文案。
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : (
            <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-amber-950">
              <p className="font-semibold">无事实资料约束</p>
              <p className="mt-1 text-sm">
                可继续生成创意草稿，但不得补充具体材质、参数、价格、功效或承诺。
              </p>
            </div>
          )}
          {factConflict ? (
            <p className="rounded-lg border border-red-300 bg-red-50 p-3 font-semibold text-red-950">
              请先处理高风险事实冲突
            </p>
          ) : null}
          {fixture.factContext.requires_confirmation ? (
            <p className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-amber-950">
              仍有候选事实等待人工确认；未确认项不会作为确定性生成约束。
            </p>
          ) : null}
          {sourceManager ?? (
            <p className="text-sm">
              <Link className="font-semibold text-[var(--brand)]" href={`/workspaces/${workspaceId}/facts`}>
                前往事实资料中心添加或确认来源
              </Link>
              。当前版本支持添加网页来源；自动联网检索尚未配置。
            </p>
          )}
        </section>
      );
    }

    if (activeStep === "references") {
      return (
        <section className="space-y-5 rounded-xl border bg-white p-5">
          <div>
            <h2 className="text-lg font-semibold">账号风格</h2>
            <p className="text-sm text-[var(--text-secondary)]">
              账号风格控制表达习惯，爆款引用只提供结构灵感，两者不会自动合并。
            </p>
            <p className="mt-2 font-medium">
              账号风格版本：{confirmedStyle ? `v${confirmedStyle.version}` : "当前记录未提供"}
            </p>
            <p className="text-sm text-[var(--text-secondary)]">
              栏目临时覆盖：{confirmedStyle?.column_campaign_id
                ? `生效于 ${confirmedStyle.column_campaign_id}`
                : "未记录栏目覆盖，使用账号默认或当前记录未提供"}
            </p>
          </div>
          <fieldset className="grid gap-3 sm:grid-cols-3">
            <legend className="mb-2 font-semibold">独立风格开关</legend>
            {[
              ["inheritTitleStyle", "沿用标题风格"],
              ["inheritCopyStyle", "沿用文案风格"],
              ["inheritCoverStyle", "沿用封面风格"],
            ].map(([key, label]) => (
              <label className="flex gap-2" key={key}>
                <input
                  checked={state[key as keyof GenerationWizardState] === true}
                  onChange={(event) => update({
                    [key]: event.target.checked,
                  })}
                  type="checkbox"
                />
                {label}
              </label>
            ))}
          </fieldset>
          <fieldset className="space-y-2">
            <legend className="font-semibold">已确认爆款素材（最多 3 条）</legend>
            {fixture.viralItems
              .filter((item) => item.generation_eligible)
              .map((item) => {
                const checked = state.viralReferenceIds.includes(item.id);
                const disabled =
                  !checked && state.viralReferenceIds.length >= 3;
                return (
                  <label className="flex gap-2 rounded-lg border p-3" key={item.id}>
                    <input
                      aria-label={item.title}
                      checked={checked}
                      disabled={disabled}
                      onChange={(event) => update({
                        viralReferenceIds: event.target.checked
                          ? [...state.viralReferenceIds, item.id].slice(0, 3)
                          : state.viralReferenceIds.filter((id) => id !== item.id),
                      })}
                      type="checkbox"
                    />
                    <span>
                      <strong>{item.title}</strong> · {item.structure_summary}
                      <span className="mt-1 block text-sm text-[var(--text-secondary)]">
                        适用场景：{item.applicable_scenarios.join("、") || "当前记录未提供"}；
                        策略标签：{item.strategy_tags.join("、") || "当前记录未提供"}；
                        推荐原因、样本数和基准范围：当前记录未提供
                      </span>
                    </span>
                  </label>
                );
              })}
            <p className="text-sm text-[var(--text-secondary)]">
              最多选择 3 条已确认素材
            </p>
          </fieldset>
          <p className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-950">
            参考图最多 3 张，每张必须声明构图、风格、人物、产品或配色用途；实际文件在封面编辑器中选择。
          </p>
          <p className="text-sm text-[var(--text-secondary)]">
            生成预设：当前记录未提供。自定义提示词和内容要点将在生成步骤作为不可信业务输入提交，不能改变事实与风控策略。
          </p>
        </section>
      );
    }

    if (activeStep === "generate") {
      if (!canWrite) {
        return (
          <section className="space-y-4 rounded-xl border bg-white p-5">
            <p>查看者只能查看生成状态，不能发起模型任务或保存草稿。</p>
            <DesktopOnlyNotice action="复杂封面编辑" />
          </section>
        );
      }
      if (factConflict) {
        return (
          <section className="rounded-xl border border-red-300 bg-red-50 p-5 text-red-950">
            <h2 className="font-semibold">请先处理高风险事实冲突</h2>
            <p className="mt-1 text-sm">
              前端不会绕过服务端事实优先级和同等级冲突门禁。
            </p>
          </section>
        );
      }
      return (
        <section className="space-y-8">
          {!generationReady ? (
            <p className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-amber-950">
              请先选择账号、生成目标与可用文本模型，并处理事实冲突。
            </p>
          ) : null}
          <TextEditor
            defaults={{
              accountId: controlledAccountId ?? "",
              columnCampaignId: state.columnId ?? "",
              factItemIds: chosenFacts.flatMap((source) =>
                source.items
                  .filter(
                    (item) =>
                      item.status === "confirmed"
                      && item.conflict_status !== "unresolved",
                  )
                  .map((item) => item.id)
              ),
              factSourceIds: state.factSourceIds,
              inheritCopyStyle: state.inheritCopyStyle,
              inheritCoverStyle: state.inheritCoverStyle,
              inheritTitleStyle: state.inheritTitleStyle,
              modelConfigId: textModel?.id ?? "",
              platform: selectedAccount?.platform ?? "douyin",
              styleProfileId: confirmedStyle?.id ?? "",
              target: state.objectiveId ?? "",
              viralReferenceIds: state.viralReferenceIds,
            }}
            deferFinalSave
            key={`${controlledAccountId}-${state.columnId}-${textModel?.id}`}
            onDraftChange={setGenerationDraft}
            workspaceId={workspaceId}
          />
          <CoverEditor />
        </section>
      );
    }

    return (
      <section className="space-y-5 rounded-xl border bg-white p-5">
        <h2 className="text-lg font-semibold">发布前复核</h2>
        <p>
          保存草稿前必须重新执行事实冲突门禁和风险扫描；高风险、OCR 失败、无有效证据或内容修改后均不能伪装为安全通过。
        </p>
        {fixture.riskScan ? (
          <RiskReport scan={fixture.riskScan} />
        ) : (
          <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-amber-950">
            <p className="font-semibold">尚未执行发布前检查</p>
            <p className="mt-1 text-sm">
              请先生成内容并执行标题、正文和封面 OCR 联合复检。
            </p>
          </div>
        )}
        {generationDraft.run ? (
          <div className="rounded-lg border p-4">
            <p className="font-semibold">
              生成状态：{generationDraft.run.status} · 采用状态：{" "}
              {generationDraft.run.adoption_status}
            </p>
            <p className="mt-1 text-sm text-[var(--text-secondary)]">
              合同 {generationDraft.run.context.model.contract_version} ·
              配置 {generationDraft.run.context.model.configuration_version} ·
              修改幅度 {(generationDraft.run.modification_magnitude * 100).toFixed(1)}%
            </p>
            {generationDraft.run.status_detail ? (
              <p className="mt-2 text-sm">{generationDraft.run.status_detail}</p>
            ) : null}
          </div>
        ) : (
          <p className="text-sm text-[var(--text-secondary)]">
            当前会话尚无可复核的生成结果。
          </p>
        )}
        {reviewError ? <p role="alert">{reviewError}</p> : null}
        {reviewMessage ? <p role="status">{reviewMessage}</p> : null}
        {canWrite && generationDraft.run?.status === "succeeded" ? (
          <div className="flex flex-wrap gap-3">
            <button
              className="rounded-lg bg-[var(--brand)] px-4 py-2 font-semibold text-white disabled:opacity-50"
              disabled={reviewBusy}
              onClick={() => saveReviewedDraft("adopted")}
              type="button"
            >
              复检并保存草稿
            </button>
            <button
              className="rounded-lg border bg-white px-4 py-2 disabled:opacity-50"
              disabled={reviewBusy}
              onClick={() => saveReviewedDraft("rejected")}
              type="button"
            >
              拒绝本稿
            </button>
          </div>
        ) : null}
        <p className="font-semibold">辅助判断，不保证通过平台审核</p>
      </section>
    );
  })();

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <PageHeader
        description="范围、事实、风格与参考、生成编辑和发布前复核依次完成；刷新只恢复不含正文、图片或凭据的安全元数据。"
        title="生成中心"
      />
      <div className="flex flex-wrap gap-2" role="navigation" aria-label="生成步骤">
        {steps.map((step, index) => {
          const activeIndex = steps.findIndex(
            (candidate) => candidate.id === activeStep,
          );
          const blocked = factConflict && index > 1;
          const marker = blocked
            ? "阻断"
            : index < activeIndex
              ? "已完成"
              : index === activeIndex
                ? "当前"
                : "";
          return canWrite ? (
            <button
              aria-current={activeStep === step.id ? "step" : undefined}
              aria-label={step.label}
              className="rounded-lg border bg-white px-3 py-2 text-sm font-semibold disabled:opacity-60"
              disabled={blocked}
              key={step.id}
              onClick={() => chooseStep(step.id)}
              type="button"
            >
              {step.label}
              {marker ? <span aria-hidden="true"> · {marker}</span> : null}
            </button>
          ) : (
            <span
              aria-current={activeStep === step.id ? "step" : undefined}
              className="rounded-lg border bg-white px-3 py-2 text-sm"
              key={step.id}
            >
              {step.label}
              {marker ? <span aria-hidden="true"> · {marker}</span> : null}
            </span>
          );
        })}
      </div>
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_260px]">
        <div>{stepPanel}</div>
        <aside className="h-fit rounded-xl border bg-white p-4 xl:sticky xl:top-20">
          <h2 className="font-semibold">当前生成范围</h2>
          <dl className="mt-3 space-y-2 text-sm">
            <div>
              <dt>平台</dt>
              <dd>{selectedAccount
                ? selectedAccount.platform === "douyin" ? "抖音" : "小红书"
                : controlledPlatform === "douyin"
                  ? "抖音"
                  : controlledPlatform === "xiaohongshu"
                    ? "小红书"
                    : "未选择"}</dd>
            </div>
            <div><dt>账号</dt><dd>{selectedAccount?.name ?? "未选择"}</dd></div>
            <div><dt>栏目</dt><dd>{state.columnId ?? "账号默认"}</dd></div>
            <div><dt>目标</dt><dd>{state.objectiveId ?? "未填写"}</dd></div>
            <div>
              <dt>事实来源</dt>
              <dd>
                {chosenFacts.length} 个；已确认事实{" "}
                {chosenFacts.flatMap((source) => source.items)
                  .filter((item) => item.status === "confirmed").length} 条
              </dd>
            </div>
            <div>
              <dt>风格继承</dt>
              <dd>
                标题 {state.inheritTitleStyle ? "开启" : "关闭"} · 文案{" "}
                {state.inheritCopyStyle ? "开启" : "关闭"} · 封面{" "}
                {state.inheritCoverStyle ? "开启" : "关闭"}
              </dd>
            </div>
            <div><dt>爆款引用</dt><dd>{state.viralReferenceIds.length} 条</dd></div>
            <div><dt>参考图用途</dt><dd>尚未在封面编辑器选择</dd></div>
            <div>
              <dt>模型</dt>
              <dd>
                {textModel ? (
                  <>
                    {textModel.model_id}{" "}
                    {textModel.experimental ? (
                      <StatusBadge tone="warning">Provider experimental</StatusBadge>
                    ) : null}
                    <span className="mt-1 block">
                      合同 {textModel.contract_version} · 配置{" "}
                      {textModel.configuration_version}
                    </span>
                  </>
                ) : "文本模型未配置"}
              </dd>
            </div>
            <div>
              <dt>风险状态</dt>
              <dd>
                {fixture.riskScan
                  ? `${fixture.riskScan.status} · ${fixture.riskScan.scanner_version}`
                  : "尚未执行本次发布前检查"}
              </dd>
            </div>
            <div>
              <dt>今日用量</dt>
              <dd>
                {fixture.modelUsageSummary
                  ? `${fixture.modelUsageSummary.real_attempts} 次真实调用；估算 ${
                      fixture.modelUsageSummary.estimated_cost_microunits
                    } 微元`
                  : "当前记录未提供"}
              </dd>
            </div>
            <div>
              <dt>预算边界</dt>
              <dd>
                {fixture.modelUsagePolicies?.length
                  ? `工作区策略 v${Math.max(
                      ...fixture.modelUsagePolicies.map((policy) => policy.version),
                    )}`
                  : "未配置独立预算策略"}
              </dd>
            </div>
          </dl>
        </aside>
      </div>
      {canWrite ? (
        <nav className="flex items-center justify-between" aria-label="生成步骤控制">
          <button
            className="rounded-lg border bg-white px-4 py-2 disabled:opacity-50"
            disabled={activeStep === "scope"}
            onClick={() => chooseStep(previousStep(activeStep))}
            type="button"
          >
            上一步
          </button>
          <button
            aria-label={
              activeStep === "references" ? "继续下一步" : undefined
            }
            className="rounded-lg bg-[var(--brand)] px-4 py-2 font-semibold text-white disabled:opacity-50"
            disabled={
              activeStep === "review"
              || (activeStep === "facts" && factConflict)
            }
            onClick={() => chooseStep(nextStep(activeStep))}
            type="button"
          >
            下一步：{steps.find((step) => step.id === nextStep(activeStep))?.label}
          </button>
        </nav>
      ) : null}
    </div>
  );
}
