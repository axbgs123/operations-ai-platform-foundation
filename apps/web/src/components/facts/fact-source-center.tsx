"use client";

import { FormEvent, useEffect, useState } from "react";

import {
  confirmFactItem,
  createFactSource,
  FactContextData,
  FactSourceData,
  getFactContext,
  listFactSources,
  uploadFactSource,
} from "@/lib/fact-api";
import { GuidedPageHeader } from "@/components/workbench/guided-page-header";
import { useWorkbenchShellContext } from "@/components/workbench/workspace-shell";
import { StatusBadge } from "@/components/workbench/ui";

const visualFactWarning = {
  simple: "图片只能帮助识别可能出现的文字或外观，不能证明面料、价格、功效、认证等事实。",
  professional: "L5 视觉推断不能升级为已验证事实，也不能单独支撑确定性生成声明。",
};

const STATUS_LABELS: Record<string, string> = {
  parsed: "解析完成",
  awaiting_fetch: "等待安全抓取",
  awaiting_model: "等待解析模型",
  failed: "解析失败",
};

function detailCapabilities(source: FactSourceData): string[] {
  const value = source.status_detail.required_capabilities;
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

export function FactSourceCenter({
  workspaceId,
  role,
}: {
  workspaceId: string;
  role?: "admin" | "editor" | "viewer";
}) {
  const [sources, setSources] = useState<FactSourceData[]>([]);
  const [context, setContext] = useState<FactContextData | null>(null);
  const [kind, setKind] = useState<"text" | "link" | "web">("text");
  const [level, setLevel] = useState<"L1" | "L2" | "L3" | "L4" | "L5">("L2");
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");
  const [content, setContent] = useState("");
  const [uploadKind, setUploadKind] = useState<"document" | "image">("document");
  const [uploadLevel, setUploadLevel] = useState<"L1" | "L2" | "L3" | "L4" | "L5">("L3");
  const [uploadTitle, setUploadTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const shellContext = useWorkbenchShellContext();
  const canWrite = (role ?? shellContext?.role ?? "admin") !== "viewer";
  const csrf = () => sessionStorage.getItem("workspace_csrf") ?? "";

  useEffect(() => {
    let active = true;
    Promise.all([listFactSources(workspaceId), getFactContext(workspaceId)])
      .then(([nextSources, nextContext]) => {
        if (!active) return;
        setSources(nextSources);
        setContext(nextContext);
      })
      .catch((caught: unknown) => {
        if (active) setError(caught instanceof Error ? caught.message : "事实资料加载失败");
      });
    return () => { active = false; };
  }, [workspaceId]);

  async function addSource(event: FormEvent) {
    event.preventDefault();
    setBusy("create");
    setError("");
    try {
      const source = await createFactSource(workspaceId, csrf(), {
        kind,
        level,
        title,
        content,
        ...(kind === "text" ? {} : { url }),
      });
      setSources((current) => [...current, source]);
      setMessage("事实来源已保存；解析结果仍需逐项确认");
      setTitle("");
      setUrl("");
      setContent("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "事实来源保存失败");
    } finally {
      setBusy("");
    }
  }

  async function upload(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    setBusy("upload");
    setError("");
    const form = new FormData();
    form.set("kind", uploadKind);
    form.set("level", uploadLevel);
    form.set("title", uploadTitle);
    form.set("file", file);
    try {
      const source = await uploadFactSource(workspaceId, csrf(), form);
      setSources((current) => [...current, source]);
      setMessage("文件已保存；可解析字段会作为候选事实显示");
      setUploadTitle("");
      setFile(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "事实文件上传失败");
    } finally {
      setBusy("");
    }
  }

  async function confirm(sourceId: string, itemId: string, fieldName: string) {
    setBusy(itemId);
    setError("");
    try {
      const confirmed = await confirmFactItem(workspaceId, itemId, csrf());
      setSources((current) => current.map((source) => (
        source.id === sourceId
          ? {
              ...source,
              items: source.items.map((item) => item.id === itemId ? confirmed : item),
            }
          : source
      )));
      setContext((current) => current ? {
        ...current,
        unconstrained_facts: false,
        confirmed_items: [...current.confirmed_items, confirmed],
      } : current);
      setContext(await getFactContext(workspaceId));
      setMessage(`已确认：${fieldName}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "候选事实确认失败");
    } finally {
      setBusy("");
    }
  }

  const factRows = sources.flatMap((source) =>
    source.items.map((item) => ({ source, item }))
  );
  return (
    <section className="mx-auto max-w-7xl space-y-6">
      <GuidedPageHeader
        context={visualFactWarning}
        pageId="facts"
        title="事实资料中心"
      />
      <section className="grid gap-2 rounded-xl border bg-white p-5 text-sm sm:grid-cols-2 lg:grid-cols-5" aria-label="事实来源等级说明">
        <p>L1：权威结构化资料</p>
        <p>L2：用户明确填写并确认</p>
        <p>L3：文档/OCR提取后人工确认</p>
        <p>L4：外部网页候选，具体参数仍需人工确认</p>
        <p>L5：视觉模型推测，只能作为候选提示</p>
      </section>
      <aside className="rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-950" role="note">
        <p className="font-semibold">当前版本支持添加网页来源，自动联网检索尚未配置</p>
        <p className="mt-1">网页正文始终是不可信数据；localhost、内网和云元数据地址会被服务端拒绝。</p>
        <p className="mt-1">生效范围：工作区通用（当前记录未提供更细范围）</p>
      </aside>
      {context?.unconstrained_facts ? (
        <p className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-amber-950">
          当前生成不受已确认事实资料约束
        </p>
      ) : null}
      <p className="rounded-xl border bg-white p-4 text-sm">
        上传资料和解析文本始终作为不可信数据处理
      </p>
      {!canWrite ? (
        <p className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">
          查看者可查看事实与冲突状态，不能添加来源或确认候选
        </p>
      ) : null}
      {error ? <p className="rounded-xl border border-red-300 bg-red-50 p-4 text-red-950" role="alert">{error}</p> : null}
      {message ? <p className="rounded-xl border border-emerald-300 bg-emerald-50 p-4 text-emerald-950" role="status">{message}</p> : null}

      {canWrite ? <div className="grid gap-6 lg:grid-cols-2">
        <form className="space-y-4 rounded-xl border bg-white p-5" onSubmit={addSource}>
          <h2 className="text-lg font-semibold">添加文字或网页来源</h2>
          <label className="block">来源类型
            <select className="mt-1 w-full rounded-lg border bg-white p-3" onChange={(event) => {
              const nextKind = event.target.value as typeof kind;
              setKind(nextKind);
              if (nextKind !== "text") setLevel("L4");
            }} value={kind}>
              <option value="text">文字说明</option>
              <option value="link">链接资料</option>
              <option value="web">网页来源（L4 候选）</option>
            </select>
          </label>
          <label className="block">资料标题
            <input className="mt-1 w-full rounded-lg border p-3" onChange={(event) => setTitle(event.target.value)} required value={title} />
          </label>
          <label className="block">来源等级
            <select className="mt-1 w-full rounded-lg border bg-white p-3" disabled={kind !== "text"} onChange={(event) => setLevel(event.target.value as typeof level)} value={level}>
              {(["L1", "L2", "L3", "L4", "L5"] as const).map((value) => <option key={value}>{value}</option>)}
            </select>
          </label>
          {kind !== "text" ? <label className="block">来源链接
            <input className="mt-1 w-full rounded-lg border p-3" onChange={(event) => setUrl(event.target.value)} required type="url" value={url} />
          </label> : null}
          <label className="block">资料正文或网页快照
            <textarea className="mt-1 min-h-32 w-full rounded-lg border p-3" onChange={(event) => setContent(event.target.value)} value={content} />
          </label>
          <button className="rounded-lg bg-[var(--brand)] px-4 py-2 font-semibold text-white" disabled={busy === "create"} type="submit">添加事实来源</button>
        </form>

        <form className="space-y-4 rounded-xl border bg-white p-5" onSubmit={upload}>
          <h2 className="text-lg font-semibold">上传文档或图片</h2>
          <label className="block">上传类型
            <select className="mt-1 w-full rounded-lg border bg-white p-3" onChange={(event) => setUploadKind(event.target.value as typeof uploadKind)} value={uploadKind}>
              <option value="document">文档</option><option value="image">图片</option>
            </select>
          </label>
          <label className="block">上传标题
            <input className="mt-1 w-full rounded-lg border p-3" onChange={(event) => setUploadTitle(event.target.value)} required value={uploadTitle} />
          </label>
          <label className="block">上传等级
            <select className="mt-1 w-full rounded-lg border bg-white p-3" onChange={(event) => setUploadLevel(event.target.value as typeof uploadLevel)} value={uploadLevel}>
              {(["L1", "L2", "L3", "L4", "L5"] as const).map((value) => <option key={value}>{value}</option>)}
            </select>
          </label>
          <label className="block">选择资料文件
            <input accept=".txt,.pdf,.docx,.png,.jpg,.jpeg,.webp" className="mt-1 block w-full" onChange={(event) => setFile(event.target.files?.[0] ?? null)} required type="file" />
          </label>
          <p className="text-sm text-[var(--text-secondary)]">图片最大 10 MiB，文档最大 20 MiB；MIME、扩展名和文件签名必须一致。</p>
          <button className="rounded-lg bg-[var(--brand)] px-4 py-2 font-semibold text-white" disabled={busy === "upload"} type="submit">上传并解析</button>
        </form>
      </div> : null}

      <section className="space-y-4">
        <h2 className="text-lg font-semibold">来源列表</h2>
        {sources.length === 0 ? <p className="rounded-xl border bg-white p-5">尚无来源。下一步：添加文字、网页、文档或图片资料。</p> : (
          <ul className="grid grid-cols-1 gap-4 lg:grid-cols-2" data-testid="fact-source-cards">
            {sources.map((source) => {
              const capabilities = detailCapabilities(source);
              const conflictCount = source.items.filter((item) => item.conflict_status !== "clear").length;
              const confirmedCount = source.items.filter((item) => item.status === "confirmed").length;
              return <li className="rounded-xl border bg-white p-5" key={source.id}>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <h3 className="font-semibold">{source.title}</h3>
                  <StatusBadge tone={source.status === "failed" ? "danger" : source.status === "parsed" ? "success" : "warning"}>
                    {source.level} · {STATUS_LABELS[source.status]}
                  </StatusBadge>
                </div>
                <dl className="mt-4 grid gap-2 text-sm">
                  <div><dt className="inline text-[var(--text-secondary)]">来源类型：</dt><dd className="inline">{source.kind}</dd></div>
                  <div><dt className="inline text-[var(--text-secondary)]">人工确认状态：</dt><dd className="inline">{confirmedCount ? `${confirmedCount} 项已确认` : "未确认"}</dd></div>
                  <div><dt className="inline text-[var(--text-secondary)]">冲突数量：</dt><dd className="inline">{conflictCount}</dd></div>
                  <div><dt className="inline text-[var(--text-secondary)]">生效范围：</dt><dd className="inline">工作区通用（当前记录未提供更细范围）</dd></div>
                  <div><dt className="inline text-[var(--text-secondary)]">创建时间：</dt><dd className="inline">{source.created_at}</dd></div>
                  <div><dt className="inline text-[var(--text-secondary)]">当前版本：</dt><dd className="inline">当前记录未提供</dd></div>
                </dl>
                {source.status === "awaiting_model" ? <p className="mt-3 text-sm text-amber-900">需要配置 {capabilities.join("、")} 模型后解析</p> : null}
                {source.source_url ? <p className="mt-3 break-all text-sm text-[var(--text-secondary)]">URL：{source.source_url}</p> : null}
                {source.file_name ? <p className="mt-3 break-all text-sm text-[var(--text-secondary)]">文件：{source.file_name} · SHA-256：{source.content_sha256}</p> : null}
                {source.published_at ? <p className="mt-1 text-sm">发布时间：{source.published_at}</p> : null}
                {source.accessed_at ? <p className="mt-1 text-sm">安全抓取时间：{source.accessed_at}</p> : null}
              </li>;
            })}
          </ul>
        )}
      </section>

      <section className="space-y-4">
        <h2 className="text-lg font-semibold">事实清单</h2>
        {factRows.length === 0 ? <p className="rounded-xl border bg-white p-5">尚无候选事实。下一步：等待来源解析或补充人工事实。</p> : (
          <ul className="grid grid-cols-1 gap-4 lg:grid-cols-2" data-testid="fact-item-cards">
            {factRows.map(({ source, item }) => {
              const confirmed = item.status === "confirmed";
              const usable = confirmed && source.level !== "L5" && item.conflict_status === "clear";
              const override = item.override_record;
              return <li className="rounded-xl border bg-white p-5" key={item.id}>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <h3 className="font-semibold">{item.field_name}：{item.value}</h3>
                  <StatusBadge tone={item.conflict_status === "unresolved" ? "danger" : confirmed ? "success" : "warning"}>
                    {confirmed ? "用户已确认" : "未确认"} · {item.conflict_status === "clear" ? "无冲突" : "存在冲突"}
                  </StatusBadge>
                </div>
                <p className="mt-3 text-sm">来源位置：{item.source_location} · 置信度 {Math.round(item.confidence * 100)}%</p>
                <p className="mt-1 text-sm">来源等级：{source.level}</p>
                <p className="mt-1 text-sm">用户确认状态：{confirmed ? "已确认" : "未确认"}</p>
                <p className="mt-1 text-sm">系统验证状态：未验证</p>
                <p className="mt-1 text-sm">冲突状态：{item.conflict_status}</p>
                <p className="mt-1 text-sm">当前是否可用于生成：{usable ? "是" : "否"}</p>
                <p className="mt-1 text-sm">覆盖记录：{override ? `操作者 ${String(override.operator_id ?? "当前记录未提供")} · 理由 ${String(override.reason ?? "当前记录未提供")} · 时间 ${String(override.created_at ?? "当前记录未提供")}` : "无"}</p>
                {source.level === "L5" ? (
                  <div className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-950">
                    <p className="font-semibold">禁止仅凭视觉推测写入确定性文案</p>
                    <p>面料、成分、价格、尺码、功效、认证、产地和安全承诺不得仅凭视觉推断。</p>
                  </div>
                ) : null}
                {item.conflict_status === "unresolved" ? <p className="mt-3 text-sm font-semibold text-red-800">同等级冲突未解决，受事实约束的生成必须暂停。</p> : null}
                {!confirmed && source.level !== "L5" && canWrite ? (
                  <button className="mt-3 rounded-lg bg-[var(--brand)] px-3 py-2 text-sm font-semibold text-white" disabled={busy === item.id} onClick={() => confirm(source.id, item.id, item.field_name)} type="button">确认{item.field_name}</button>
                ) : null}
              </li>;
            })}
          </ul>
        )}
      </section>
    </section>
  );
}
