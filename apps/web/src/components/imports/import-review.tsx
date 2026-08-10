"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import {
  loadColumnCampaigns,
  type ColumnCampaign,
} from "@/lib/account-api";
import {
  confirmImport,
  ImportBatchData,
  previewManualImport,
  previewTabularImport,
  readImportBatch,
  updateImportMapping,
  updateImportRow,
} from "@/lib/import-api";


const STATUS_LABELS = {
  new: "新增",
  update: "更新",
  suspected_duplicate: "疑似重复",
  failed: "失败",
} as const;


function normalizedTitle(row: ImportBatchData["rows"][number]) {
  const value = row.normalized_data.title;
  return typeof value === "string" ? value : "";
}

export function ImportReview({
  workspaceId,
  accountId,
  platform,
  mode,
  initialBatchId,
}: {
  workspaceId: string;
  accountId: string;
  platform: "douyin" | "xiaohongshu";
  mode?: "manual" | "tabular";
  initialBatchId?: string;
}) {
  const [contentType, setContentType] = useState<"video" | "image_text">("video");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportBatchData | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [titleDrafts, setTitleDrafts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [columns, setColumns] = useState<ColumnCampaign[]>([]);

  const csrf = () => sessionStorage.getItem("workspace_csrf") ?? "";
  const acceptPreview = useCallback((next: ImportBatchData) => {
    setPreview(next);
    setTitleDrafts(
      Object.fromEntries(next.rows.map((row) => [row.id, normalizedTitle(row)])),
    );
    setSelected(new Set());
  }, []);

  useEffect(() => {
    if (mode === "tabular") return;
    let active = true;
    void loadColumnCampaigns(workspaceId, accountId)
      .then((items) => {
        if (active) setColumns(items);
      })
      .catch(() => {
        if (active) setError("栏目加载失败，请确认账号范围后重试");
      });
    return () => {
      active = false;
    };
  }, [accountId, mode, workspaceId]);

  useEffect(() => {
    if (!initialBatchId) return;
    let active = true;
    void readImportBatch(initialBatchId)
      .then((batch) => {
        if (!active) return;
        if (
          batch.account_id !== accountId
          || batch.platform !== platform
        ) {
          setError("暂存预览与当前平台或账号不匹配");
          return;
        }
        acceptPreview(batch);
      })
      .catch(() => {
        if (active) setError("无法恢复该暂存预览");
      });
    return () => {
      active = false;
    };
  }, [acceptPreview, accountId, initialBatchId, platform]);

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      acceptPreview(
        await previewTabularImport(
          workspaceId,
          accountId,
          platform,
          contentType,
          file,
          csrf(),
        ),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "预览失败");
    } finally {
      setBusy(false);
    }
  }

  async function manual(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    setMessage("");
    try {
      acceptPreview(
        await previewManualImport(
          workspaceId,
          {
            account_id: accountId,
            platform,
            content_type: contentType,
            rows: [
              {
                title: String(form.get("title") ?? ""),
                body: String(form.get("body") ?? ""),
                column_campaign_id:
                  String(form.get("columnCampaignId") ?? "") || null,
                work_url: String(form.get("workUrl") ?? "") || null,
                published_at: new Date(
                  String(form.get("publishedAt") ?? ""),
                ).toISOString(),
                collected_at: new Date(
                  String(form.get("collectedAt") ?? ""),
                ).toISOString(),
                metrics: { views: String(form.get("views") ?? "") },
              },
            ],
          },
          csrf(),
        ),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "手动预览失败");
    } finally {
      setBusy(false);
    }
  }

  async function applyHighConfidenceMappings() {
    if (!preview) return;
    const mapping = Object.fromEntries(
      preview.header_mappings
        .filter((item) => item.high_confidence && item.target_field)
        .map((item) => [item.source_header, item.target_field as string]),
    );
    try {
      acceptPreview(await updateImportMapping(preview.id, mapping, csrf()));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "映射更新失败");
    }
  }

  async function saveRow(rowId: string) {
    if (!preview) return;
    try {
      const next = await updateImportRow(
        preview.id,
        rowId,
        { title: titleDrafts[rowId] ?? "" },
        csrf(),
      );
      setPreview(next);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "行修正失败");
    }
  }

  function toggleRow(rowId: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(rowId)) next.delete(rowId);
      else next.add(rowId);
      return next;
    });
  }

  async function confirmSelected() {
    if (!preview || selected.size === 0) return;
    setBusy(true);
    setError("");
    try {
      const result = await confirmImport(preview.id, [...selected], csrf());
      setMessage(
        `已写入 ${result.content_ids.length} 条内容和 ${result.snapshot_ids.length} 条指标快照`,
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "确认失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="space-y-8">
      <header>
        <p className="text-sm font-medium text-cyan-300">人工确认工作流</p>
        <h1 className="mt-2 text-3xl font-semibold">运营数据暂存导入</h1>
        <p className="mt-3 text-slate-400">预览不会写入正式内容或指标快照</p>
      </header>

      <div className={`grid gap-6 ${mode ? "" : "lg:grid-cols-2"}`}>
        {mode !== "manual" ? (
        <form className="space-y-4 rounded-xl border border-[var(--border)] bg-white p-6 text-[var(--text-primary)]" onSubmit={upload}>
          <h2 className="text-xl font-semibold">CSV / Excel 批量导入</h2>
          <label className="block">
            内容类型
            <select className="mt-2 w-full px-4 py-3" onChange={(event) => setContentType(event.target.value as "video" | "image_text")} value={contentType}>
              <option value="video">视频</option>
              <option value="image_text">图文</option>
            </select>
          </label>
          <label className="block">
            CSV 或 Excel 文件
            <input accept=".csv,.xlsx" className="mt-2 block w-full text-sm" onChange={(event) => setFile(event.target.files?.[0] ?? null)} type="file" />
          </label>
          <button className="rounded-xl bg-cyan-400 px-5 py-3 font-semibold text-slate-950 disabled:opacity-50" disabled={!file || busy} type="submit">生成暂存预览</button>
        </form>
        ) : null}

        {mode !== "tabular" ? (
        <form className="space-y-4 rounded-xl border border-[var(--border)] bg-white p-6 text-[var(--text-primary)]" onSubmit={manual}>
          <h2 className="text-xl font-semibold">手动录入一行</h2>
          <label className="block">
            栏目/活动
            <select
              className="mt-2 w-full px-4 py-3"
              name="columnCampaignId"
            >
              <option value="">使用账号默认</option>
              {columns.map((column) => (
                <option key={column.id} value={column.id}>
                  {column.name}
                </option>
              ))}
            </select>
          </label>
          <label className="block">标题<input className="mt-2 w-full px-4 py-3" name="title" required /></label>
          <label className="block">正文<textarea className="mt-2 w-full px-4 py-3" name="body" /></label>
          <label className="block">作品链接<input className="mt-2 w-full px-4 py-3" name="workUrl" type="url" /></label>
          <div className="grid gap-3 sm:grid-cols-2">
            <label>发布时间<input className="mt-2 w-full px-3 py-2" name="publishedAt" required type="datetime-local" /></label>
            <label>数据时间<input className="mt-2 w-full px-3 py-2" name="collectedAt" required type="datetime-local" /></label>
          </div>
          <label className="block">播放/阅读量<input className="mt-2 w-full px-4 py-3" min="0" name="views" required type="number" /></label>
          <button className="rounded-xl border border-cyan-400 px-5 py-3 font-semibold text-cyan-300" disabled={busy} type="submit">生成手动暂存预览</button>
        </form>
        ) : null}
      </div>

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

      {preview ? (
        <div className="space-y-5">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {Object.entries(STATUS_LABELS).map(([status, label]) => (
              <div className="rounded-2xl border border-slate-800 bg-slate-900 p-4" key={status}>
                <p className="text-sm text-slate-400">{label}</p>
                <p className="mt-1 text-2xl font-semibold">{label} {preview.summary[status as keyof typeof preview.summary]}</p>
              </div>
            ))}
          </div>

          {preview.header_mappings.length ? (
            <div className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-xl font-semibold">表头映射建议</h2>
                <button className="rounded-xl border border-violet-400 px-4 py-2 text-violet-200" onClick={applyHighConfidenceMappings} type="button">采用所有高置信度映射</button>
              </div>
              <ul className="mt-4 grid gap-2 sm:grid-cols-2">
                {preview.header_mappings.map((mapping) => (
                  <li className="rounded-xl bg-slate-950 px-4 py-3 text-sm" key={mapping.source_header}>
                    {mapping.source_header} → {mapping.target_field ?? "未映射"}
                    {mapping.high_confidence ? <span className="ml-2 text-emerald-300">高置信度</span> : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          <div className="space-y-3">
            {preview.rows.map((row) => (
              <article className="rounded-2xl border border-slate-800 bg-slate-900 p-5" key={row.id}>
                <div className="flex flex-wrap items-center gap-4">
                  <label className="flex items-center gap-2">
                    <input aria-label={`选择第 ${row.row_number} 行`} checked={selected.has(row.id)} disabled={row.status === "failed"} onChange={() => toggleRow(row.id)} type="checkbox" />
                    第 {row.row_number} 行
                  </label>
                  <span className="rounded-full bg-slate-800 px-3 py-1 text-sm">{STATUS_LABELS[row.status]}</span>
                  {row.dedupe_reason ? <span className="text-sm text-amber-300">{row.dedupe_reason}</span> : null}
                </div>
                <div className="mt-4 flex flex-col gap-3 sm:flex-row">
                  <label className="flex-1">标题<input aria-label={`第 ${row.row_number} 行标题`} className="mt-2 w-full px-4 py-3" onChange={(event) => setTitleDrafts((current) => ({ ...current, [row.id]: event.target.value }))} value={titleDrafts[row.id] ?? ""} /></label>
                  <button className="self-end rounded-xl border border-slate-600 px-4 py-3" onClick={() => saveRow(row.id)} type="button">保存第 {row.row_number} 行修正</button>
                </div>
                {row.errors.length ? (
                  <ul className="mt-3 text-sm text-rose-300">
                    {row.errors.map((item) => <li key={`${item.field}:${item.message}`}>{item.message}</li>)}
                  </ul>
                ) : null}
              </article>
            ))}
          </div>

          <button className="rounded-xl bg-emerald-400 px-6 py-3 font-semibold text-slate-950 disabled:opacity-40" disabled={selected.size === 0 || busy} onClick={confirmSelected} type="button">人工确认并写入正式数据</button>
        </div>
      ) : null}
    </section>
  );
}
