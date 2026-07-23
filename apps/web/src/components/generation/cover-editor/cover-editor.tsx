"use client";

import { FormEvent, useState } from "react";


type CoverMode = "template" | "ai_visual" | "hybrid" | "custom";
type ReferencePurpose =
  | "composition"
  | "style"
  | "person"
  | "product"
  | "palette";

const purposeLabels: Record<ReferencePurpose, string> = {
  composition: "构图",
  style: "风格",
  person: "人物",
  product: "产品",
  palette: "配色",
};

export function CoverEditor() {
  const [mode, setMode] = useState<CoverMode>("template");
  const [size, setSize] = useState("1080x1440");
  const [prompt, setPrompt] = useState("");
  const [headline, setHeadline] = useState("");
  const [subtitle, setSubtitle] = useState("");
  const [reference, setReference] = useState<File | null>(null);
  const [purpose, setPurpose] = useState<ReferencePurpose>("composition");
  const [logo, setLogo] = useState<File | null>(null);
  const [preservePerson, setPreservePerson] = useState(false);
  const [preserveProduct, setPreserveProduct] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [consented, setConsented] = useState(false);
  const [generated, setGenerated] = useState(false);

  function review(event: FormEvent) {
    event.preventDefault();
    setConsented(false);
    setGenerated(false);
    setReviewing(true);
  }

  function generate() {
    if (!consented) return;
    setGenerated(true);
  }

  return (
    <section className="space-y-6 rounded-3xl border border-slate-800 bg-slate-900 p-6">
      <header>
        <p className="text-sm font-medium text-fuchsia-300">
          四种模式 · 准确中文排版
        </p>
        <h2 className="mt-2 text-2xl font-semibold">封面编辑器</h2>
        <p className="mt-2 text-sm text-slate-400">
          图片模型只生成背景或主体，最终中文、Logo 与品牌元素由程序叠加。
        </p>
      </header>

      <form className="grid gap-4 sm:grid-cols-2" onSubmit={review}>
        <label className="space-y-2 text-sm">
          封面模式
          <select
            aria-label="封面模式"
            className="w-full rounded-lg bg-slate-950 p-3"
            onChange={(event) => setMode(event.target.value as CoverMode)}
            value={mode}
          >
            <option value="template">模板模式</option>
            <option value="ai_visual">AI 视觉模式</option>
            <option value="hybrid">混合模式</option>
            <option value="custom">自定义模式</option>
          </select>
        </label>
        <label className="space-y-2 text-sm">
          封面尺寸
          <select
            className="w-full rounded-lg bg-slate-950 p-3"
            onChange={(event) => setSize(event.target.value)}
            value={size}
          >
            <option value="1080x1440">1080 × 1440</option>
            <option value="1080x1920">1080 × 1920</option>
            <option value="1080x1080">1080 × 1080</option>
          </select>
        </label>
        <label className="space-y-2 text-sm sm:col-span-2">
          视觉提示词
          <textarea
            aria-label="视觉提示词"
            className="min-h-24 w-full rounded-lg bg-slate-950 p-3"
            onChange={(event) => setPrompt(event.target.value)}
            required
            value={prompt}
          />
        </label>
        <label className="space-y-2 text-sm">
          封面主标题
          <input
            aria-label="封面主标题"
            className="w-full rounded-lg bg-slate-950 p-3"
            onChange={(event) => setHeadline(event.target.value)}
            required
            value={headline}
          />
        </label>
        <label className="space-y-2 text-sm">
          副标题
          <input
            className="w-full rounded-lg bg-slate-950 p-3"
            onChange={(event) => setSubtitle(event.target.value)}
            value={subtitle}
          />
        </label>
        <label className="space-y-2 text-sm">
          参考图文件
          <input
            accept="image/*"
            aria-label="参考图文件"
            className="block w-full text-slate-300"
            onChange={(event) => setReference(event.target.files?.[0] ?? null)}
            type="file"
          />
        </label>
        <label className="space-y-2 text-sm">
          参考图用途
          <select
            aria-label="参考图用途"
            className="w-full rounded-lg bg-slate-950 p-3"
            onChange={(event) =>
              setPurpose(event.target.value as ReferencePurpose)
            }
            value={purpose}
          >
            {Object.entries(purposeLabels).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-2 text-sm sm:col-span-2">
          Logo 文件
          <input
            accept="image/*"
            aria-label="Logo 文件"
            className="block w-full text-slate-300"
            onChange={(event) => setLogo(event.target.files?.[0] ?? null)}
            type="file"
          />
        </label>
        {mode === "hybrid" ? (
          <fieldset className="flex gap-5 rounded-xl border border-slate-700 p-4 sm:col-span-2">
            <legend className="px-2 text-sm">主体保留规则</legend>
            <label className="flex items-center gap-2 text-sm">
              <input
                checked={preservePerson}
                onChange={(event) => setPreservePerson(event.target.checked)}
                type="checkbox"
              />
              保留人物
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                checked={preserveProduct}
                onChange={(event) => setPreserveProduct(event.target.checked)}
                type="checkbox"
              />
              保留产品
            </label>
          </fieldset>
        ) : null}
        <button
          className="rounded-xl bg-fuchsia-400 px-5 py-3 font-semibold text-slate-950 sm:col-span-2"
          type="submit"
        >
          检查发送范围
        </button>
      </form>

      {reviewing ? (
        <article className="space-y-4 rounded-2xl border border-amber-700 bg-amber-950/30 p-5">
          <h3 className="text-lg font-semibold text-amber-200">
            发送给图片模型的数据
          </h3>
          {mode === "template" ? (
            <p className="text-sm text-slate-300">
              模板模式不调用图片模型，提示词与参考图仅用于本次本地排版。
            </p>
          ) : (
            <>
              <p className="text-sm text-slate-300">{prompt}</p>
              <p className="text-sm text-slate-300">
                {reference
                  ? `${reference.name} · ${purposeLabels[purpose]}`
                  : "未选择参考图"}
              </p>
            </>
          )}
          <p className="font-medium text-emerald-300">
            最终中文、Logo 和品牌元素不会发送给图片模型
          </p>
          {logo ? (
            <p className="text-sm text-slate-300">
              {logo.name} · 仅由程序叠加
            </p>
          ) : null}
          {mode === "hybrid" ? (
            <p className="text-sm text-slate-300">
              保留规则：人物 {preservePerson ? "开启" : "关闭"}，产品{" "}
              {preserveProduct ? "开启" : "关闭"}
            </p>
          ) : null}
          <label className="flex items-center gap-2 text-sm">
            <input
              aria-label="我已确认发送范围"
              checked={consented}
              onChange={(event) => setConsented(event.target.checked)}
              type="checkbox"
            />
            我已确认发送范围
          </label>
          <button
            className="rounded-lg bg-emerald-400 px-4 py-2 font-semibold text-slate-950 disabled:opacity-40"
            disabled={!consented}
            onClick={generate}
            type="button"
          >
            确认并生成 Mock 封面
          </button>
        </article>
      ) : null}

      {generated ? (
        <article
          className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-sky-950 via-cyan-900 to-fuchsia-950 p-8"
          style={{ aspectRatio: size.replace("x", " / ") }}
        >
          <p className="text-sm text-cyan-200">
            Mock 视觉层 · 最终文字由程序叠加
          </p>
          <h3 className="mt-8 max-w-xl text-4xl font-semibold">{headline}</h3>
          {subtitle ? <p className="mt-4 text-xl text-cyan-100">{subtitle}</p> : null}
          <p className="absolute bottom-8 text-sm text-cyan-200">示例品牌</p>
        </article>
      ) : null}
    </section>
  );
}
