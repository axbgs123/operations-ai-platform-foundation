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

export function FactSourceCenter({ workspaceId }: { workspaceId: string }) {
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

  return (
    <section className="space-y-8">
      <header>
        <p className="text-sm font-medium text-cyan-300">来源可追溯 · 人工确认 · 不可信输入隔离</p>
        <h1 className="mt-2 text-3xl font-semibold">事实资料中心</h1>
        <p className="mt-3 text-slate-400">系统只约束内容与已确认资料一致，不证明资料本身客观真实。</p>
      </header>

      {context?.unconstrained_facts ? (
        <p className="rounded-2xl border border-amber-500 bg-amber-950/50 p-4 text-amber-200">
          当前生成不受已确认事实资料约束
        </p>
      ) : null}
      <p className="rounded-2xl bg-slate-900 p-4 text-sm text-slate-300">
        上传资料和解析文本始终作为不可信数据处理
      </p>
      {error ? <p className="rounded-xl bg-rose-950/60 p-4 text-rose-300">{error}</p> : null}
      {message ? <p className="rounded-xl bg-emerald-950/60 p-4 text-emerald-300">{message}</p> : null}

      <div className="grid gap-6 lg:grid-cols-2">
        <form className="space-y-4 rounded-3xl border border-slate-800 bg-slate-900 p-6" onSubmit={addSource}>
          <h2 className="text-xl font-semibold">文字、链接或联网快照</h2>
          <label className="block">来源类型
            <select className="mt-1 w-full rounded-xl bg-slate-950 p-3" onChange={(event) => {
              const nextKind = event.target.value as typeof kind;
              setKind(nextKind);
              if (nextKind !== "text") setLevel("L4");
            }} value={kind}>
              <option value="text">文字说明</option><option value="link">链接资料</option><option value="web">联网来源快照</option>
            </select>
          </label>
          <label className="block">资料标题
            <input className="mt-1 w-full rounded-xl bg-slate-950 p-3" onChange={(event) => setTitle(event.target.value)} required value={title} />
          </label>
          <label className="block">来源等级
            <select className="mt-1 w-full rounded-xl bg-slate-950 p-3" disabled={kind !== "text"} onChange={(event) => setLevel(event.target.value as typeof level)} value={level}>
              {(["L1", "L2", "L3", "L4", "L5"] as const).map((value) => <option key={value}>{value}</option>)}
            </select>
          </label>
          {kind !== "text" ? <label className="block">来源链接
            <input className="mt-1 w-full rounded-xl bg-slate-950 p-3" onChange={(event) => setUrl(event.target.value)} required type="url" value={url} />
          </label> : null}
          <label className="block">资料正文或网页快照
            <textarea className="mt-1 min-h-32 w-full rounded-xl bg-slate-950 p-3" onChange={(event) => setContent(event.target.value)} value={content} />
          </label>
          <button className="rounded-xl bg-cyan-400 px-4 py-2 font-semibold text-slate-950" disabled={busy === "create"} type="submit">添加事实来源</button>
        </form>

        <form className="space-y-4 rounded-3xl border border-slate-800 bg-slate-900 p-6" onSubmit={upload}>
          <h2 className="text-xl font-semibold">文档或图片</h2>
          <label className="block">上传类型
            <select className="mt-1 w-full rounded-xl bg-slate-950 p-3" onChange={(event) => setUploadKind(event.target.value as typeof uploadKind)} value={uploadKind}>
              <option value="document">文档</option><option value="image">图片</option>
            </select>
          </label>
          <label className="block">上传标题
            <input className="mt-1 w-full rounded-xl bg-slate-950 p-3" onChange={(event) => setUploadTitle(event.target.value)} required value={uploadTitle} />
          </label>
          <label className="block">上传等级
            <select className="mt-1 w-full rounded-xl bg-slate-950 p-3" onChange={(event) => setUploadLevel(event.target.value as typeof uploadLevel)} value={uploadLevel}>
              {(["L1", "L2", "L3", "L4", "L5"] as const).map((value) => <option key={value}>{value}</option>)}
            </select>
          </label>
          <label className="block">选择资料文件
            <input accept=".txt,.pdf,.docx,.png,.jpg,.jpeg,.webp" className="mt-1 block w-full" onChange={(event) => setFile(event.target.files?.[0] ?? null)} required type="file" />
          </label>
          <p className="text-sm text-slate-400">图片最大 10 MiB，文档最大 20 MiB；MIME、扩展名和文件签名必须一致。</p>
          <button className="rounded-xl bg-fuchsia-400 px-4 py-2 font-semibold text-slate-950" disabled={busy === "upload"} type="submit">上传并解析</button>
        </form>
      </div>

      <section className="space-y-4">
        <h2 className="text-xl font-semibold">来源与候选事实</h2>
        {sources.map((source) => {
          const capabilities = detailCapabilities(source);
          return <article className="rounded-3xl border border-slate-800 bg-slate-900 p-6" key={source.id}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h3 className="font-semibold">{source.title}</h3>
              <span className="text-sm text-cyan-300">{source.level} · {STATUS_LABELS[source.status]}</span>
            </div>
            {source.status === "awaiting_model" ? (
              <p className="mt-3 text-amber-300">需要配置 {capabilities.join("、")} 模型后解析</p>
            ) : null}
            {source.source_url ? <p className="mt-3 break-all text-sm text-slate-400">URL：{source.source_url}</p> : null}
            {source.file_name ? <p className="mt-3 break-all text-sm text-slate-400">文件：{source.file_name} · SHA-256：{source.content_sha256}</p> : null}
            {source.published_at ? <p className="mt-1 text-sm text-slate-400">发布时间：{source.published_at}</p> : null}
            {source.accessed_at ? <p className="mt-1 text-sm text-slate-400">安全抓取时间：{source.accessed_at}</p> : null}
            <ul className="mt-4 space-y-3">
              {source.items.map((item) => <li className="rounded-xl bg-slate-950 p-4" key={item.id}>
                <p>{item.field_name}：{item.value}</p>
                <p className="mt-1 text-xs text-slate-500">来源位置：{item.source_location} · 置信度 {Math.round(item.confidence * 100)}%</p>
                {item.status === "candidate" ? <button className="mt-3 rounded-lg bg-emerald-400 px-3 py-2 text-sm font-semibold text-slate-950" disabled={busy === item.id} onClick={() => confirm(source.id, item.id, item.field_name)} type="button">确认{item.field_name}</button> : <span className="mt-3 block text-sm text-emerald-300">已确认</span>}
              </li>)}
            </ul>
          </article>;
        })}
      </section>
    </section>
  );
}
