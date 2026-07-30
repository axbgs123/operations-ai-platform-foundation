"use client";

import { FormEvent, useEffect, useState } from "react";

import {
  confirmImport,
  ImportBatchData,
  readImportBatch,
  stageScreenshotRecognition,
  updateImportRow,
} from "@/lib/import-api";


type Candidate = { key: string; value: string; confidence: number };

function candidates(batch: ImportBatchData | null): Candidate[] {
  const value = batch?.rows[0]?.raw_data.metric_candidates;
  if (!Array.isArray(value)) return [];
  return value.filter(
    (item): item is Candidate =>
      typeof item === "object" &&
      item !== null &&
      typeof item.key === "string" &&
      typeof item.value === "string" &&
      typeof item.confidence === "number",
  );
}

function unmappedText(batch: ImportBatchData | null): string[] {
  const value = batch?.rows[0]?.raw_data.unmapped_text;
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

export function ScreenshotReview({
  workspaceId,
  accountId,
  platform,
  initialBatchId,
}: {
  workspaceId: string;
  accountId: string;
  platform: "douyin" | "xiaohongshu";
  initialBatchId?: string;
}) {
  const [batch, setBatch] = useState<ImportBatchData | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [corrections, setCorrections] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const csrf = () => sessionStorage.getItem("workspace_csrf") ?? "";

  useEffect(() => {
    if (!initialBatchId) return;
    let active = true;
    void readImportBatch(initialBatchId)
      .then((next) => {
        if (!active) return;
        if (
          next.account_id !== accountId
          || next.platform !== platform
          || next.source_kind !== "screenshot"
        ) {
          setError("截图任务与当前平台或账号不匹配");
          return;
        }
        setBatch(next);
      })
      .catch(() => {
        if (active) setError("无法恢复该截图识别任务");
      });
    return () => {
      active = false;
    };
  }, [accountId, initialBatchId, platform]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return;
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    try {
      setBatch(
        await stageScreenshotRecognition(
          workspaceId,
          {
            accountId,
            platform,
            contentType: form.get("contentType") as "video" | "image_text",
            title: String(form.get("title") ?? ""),
            body: String(form.get("body") ?? ""),
            publishedAt: new Date(
              String(form.get("publishedAt") ?? ""),
            ).toISOString(),
            collectedAt: new Date(
              String(form.get("collectedAt") ?? ""),
            ).toISOString(),
            retentionPolicy: form.get("retentionPolicy") as
              | "delete_after_confirm"
              | "retain_as_evidence",
            file,
          },
          csrf(),
        ),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "截图上传失败");
    } finally {
      setBusy(false);
    }
  }

  async function refresh() {
    if (!batch) return;
    try {
      setBatch(await readImportBatch(batch.id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "刷新失败");
    }
  }

  async function saveCorrections() {
    const row = batch?.rows[0];
    if (!batch || !row) return;
    const current = row.normalized_data.metrics;
    const metrics = {
      ...(typeof current === "object" && current !== null ? current : {}),
      ...corrections,
    };
    try {
      setBatch(
        await updateImportRow(batch.id, row.id, { metrics }, csrf()),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "人工修正失败");
    }
  }

  async function confirm() {
    const row = batch?.rows[0];
    if (!batch || !row || !selected) return;
    setBusy(true);
    try {
      const result = await confirmImport(batch.id, [row.id], csrf());
      setMessage(`已确认 ${result.snapshot_ids.length} 条截图指标快照`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "确认失败");
    } finally {
      setBusy(false);
    }
  }

  const recognized = candidates(batch);
  const row = batch?.rows[0];

  return (
    <section className="mt-10 space-y-5 border-t border-slate-800 pt-10">
      <header>
        <p className="text-sm font-medium text-violet-300">结构化视觉识别</p>
        <h2 className="mt-2 text-2xl font-semibold">截图识别暂存区</h2>
        <p className="mt-2 text-sm text-slate-400">
          低置信度字段不会自动采用，识别完成后仍需人工确认。
        </p>
        <p className="mt-2 text-sm text-amber-200">
          真实模式会将截图发送到阿里云百炼所选地域并产生模型调用费用；图片可能含敏感信息，请先确认遮挡或裁剪范围。Mock 模式不调用外部付费模型。
        </p>
      </header>

      <form
        className="grid gap-4 rounded-3xl border border-slate-800 bg-slate-900 p-6 sm:grid-cols-2"
        onSubmit={submit}
      >
        <label className="sm:col-span-2">
          截图文件
          <input
            accept="image/png,image/jpeg,image/webp"
            className="mt-2 block w-full"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            type="file"
          />
        </label>
        <label>
          截图对应标题
          <input className="mt-2 w-full rounded-xl bg-slate-950 px-4 py-3" name="title" required />
        </label>
        <label>
          内容类型
          <select className="mt-2 w-full rounded-xl bg-slate-950 px-4 py-3" name="contentType">
            <option value="video">视频</option>
            <option value="image_text">图文</option>
          </select>
        </label>
        <label>
          截图对应发布时间
          <input className="mt-2 w-full rounded-xl bg-slate-950 px-4 py-3" name="publishedAt" required type="datetime-local" />
        </label>
        <label>
          截图数据时间
          <input className="mt-2 w-full rounded-xl bg-slate-950 px-4 py-3" name="collectedAt" required type="datetime-local" />
        </label>
        <label>
          确认后的截图策略
          <select className="mt-2 w-full rounded-xl bg-slate-950 px-4 py-3" name="retentionPolicy">
            <option value="delete_after_confirm">确认后立即删除</option>
            <option value="retain_as_evidence">保留为识别证据</option>
          </select>
        </label>
        <label>
          备注
          <input className="mt-2 w-full rounded-xl bg-slate-950 px-4 py-3" name="body" />
        </label>
        <button className="rounded-xl bg-violet-400 px-5 py-3 font-semibold text-slate-950 disabled:opacity-50 sm:col-span-2" disabled={!file || busy} type="submit">
          上传并开始识别
        </button>
      </form>

      {error ? (
        <p className="rounded-xl bg-rose-950/60 p-4 text-rose-300" role="alert">
          {error}
        </p>
      ) : null}
      {message ? (
        <p
          aria-live="polite"
          className="rounded-xl bg-emerald-950/60 p-4 text-emerald-300"
          role="status"
        >
          {message}
        </p>
      ) : null}
      {batch?.recognition_status === "pending" || batch?.recognition_status === "processing" ? (
        <div
          aria-live="polite"
          className="flex items-center gap-4 rounded-2xl bg-slate-900 p-5"
          role="status"
        >
          <p><span>识别排队中</span> · {batch.provider_mode === "mock" ? "Mock（无外部调用）" : `阿里云百炼 ${batch.region ?? "未配置地域"}`}</p>
          <button className="rounded-xl border border-violet-400 px-4 py-2" onClick={refresh} type="button">刷新识别结果</button>
        </div>
      ) : null}
      {batch?.recognition_status === "failed" ? (
        <p className="rounded-xl bg-rose-950/60 p-4 text-rose-300">识别失败，原截图仍保留，可稍后重试。</p>
      ) : null}
      {batch?.recognition_status === "ready" && row ? (
        <div className="space-y-4 rounded-3xl border border-slate-800 bg-slate-900 p-6">
          <h3 className="text-xl font-semibold">识别完成，等待人工确认</h3>
          {row.errors.length ? (
            <ul className="rounded-xl bg-rose-950/60 p-4 text-sm text-rose-300">
              {row.errors.map((item) => (
                <li key={`${item.field}:${item.message}`}>{item.message}</li>
              ))}
            </ul>
          ) : null}
          <ul className="space-y-2">
            {recognized.map((candidate) => (
              <li key={candidate.key}>
                {candidate.key}：{candidate.value} · {Math.round(candidate.confidence * 100)}%
                {candidate.confidence < 0.8 ? "（未采用）" : ""}
              </li>
            ))}
          </ul>
          {unmappedText(batch).length ? (
            <div className="rounded-xl bg-slate-950 p-4 text-sm text-slate-300">
              <p>未映射 OCR 文字（仅供人工查看，不写入正式指标）：</p>
              <ul>{unmappedText(batch).map((item) => <li key={item}>{item}</li>)}</ul>
            </div>
          ) : null}
          {recognized.filter((candidate) => candidate.confidence < 0.8).map((candidate) => (
            <label className="block" key={candidate.key}>
              补正 {candidate.key}
              <input
                aria-label={`补正 ${candidate.key}`}
                className="mt-2 w-full rounded-xl bg-slate-950 px-4 py-3"
                onChange={(event) => setCorrections((current) => ({ ...current, [candidate.key]: event.target.value }))}
                value={corrections[candidate.key] ?? ""}
              />
            </label>
          ))}
          <button className="rounded-xl border border-slate-600 px-4 py-3" onClick={saveCorrections} type="button">保存人工修正</button>
          <label className="flex items-center gap-2">
            <input aria-label="选择识别结果" checked={selected} disabled={row.status === "failed"} onChange={(event) => setSelected(event.target.checked)} type="checkbox" />
            选择识别结果
          </label>
          <button className="rounded-xl bg-emerald-400 px-5 py-3 font-semibold text-slate-950 disabled:opacity-40" disabled={!selected || busy || row.status === "failed"} onClick={confirm} type="button">人工确认截图识别结果</button>
        </div>
      ) : null}
    </section>
  );
}
