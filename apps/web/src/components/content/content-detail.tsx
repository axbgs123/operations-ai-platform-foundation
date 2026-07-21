"use client";

import { ChangeEvent, useState } from "react";

import { ContentData, deleteContent, updateContent, uploadContentAsset } from "@/lib/content-api";

export type ContentDetailData = ContentData;

export function ContentDetail({ initialContent }: { initialContent: ContentDetailData }) {
  const [content, setContent] = useState(initialContent);
  const [title, setTitle] = useState(initialContent.title);
  const [body, setBody] = useState(initialContent.body);
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState(false);

  const csrf = () => sessionStorage.getItem("workspace_csrf") ?? "";

  async function mutate(changes: Record<string, unknown>, success: string) {
    setPending(true);
    setMessage("");
    try {
      const updated = await updateContent(content.id, changes, csrf());
      setContent(updated);
      setTitle(updated.title);
      setBody(updated.body);
      setMessage(success);
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "操作失败");
    } finally {
      setPending(false);
    }
  }

  async function remove() {
    setPending(true);
    try {
      await deleteContent(content.id, csrf());
      setContent({ ...content, deleted_at: new Date().toISOString() });
      setMessage("已移入回收站");
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "删除失败");
    } finally {
      setPending(false);
    }
  }

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setPending(true);
    try {
      const asset = await uploadContentAsset(content.id, file, "screenshot", csrf());
      setContent({ ...content, assets: [...content.assets, asset] });
      setMessage("截图已上传，可用于后续识别");
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "上传失败");
    } finally {
      setPending(false);
    }
  }

  const lifecycle = content.deleted_at
    ? "回收站"
    : content.status === "published"
      ? "最终发布版"
      : content.status === "archived"
        ? "已归档"
        : "当前草稿";
  const cover = content.assets.find((asset) => asset.category === "cover");

  return (
    <main className="min-h-screen bg-slate-950 px-6 py-10 text-slate-100">
      <div className="mx-auto max-w-6xl space-y-6">
        <header className="rounded-3xl border border-slate-800 bg-slate-900 p-7">
          <div className="flex flex-wrap items-center gap-3 text-sm text-slate-400">
            <span>{content.platform === "douyin" ? "抖音" : "小红书"} · {content.account_name}</span>
            <span>栏目：{content.column_campaign_name ?? "账号默认"}</span>
            <span>发布时间：{content.published_at ? new Date(content.published_at).toLocaleString("zh-CN") : "未发布"}</span>
          </div>
          <h1 className="mt-4 text-3xl font-semibold">{title}</h1>
          <span className="mt-4 inline-block rounded-full bg-cyan-400/10 px-3 py-1 text-sm text-cyan-300">{lifecycle}</span>
        </header>

        <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
          <section className="space-y-5 rounded-3xl border border-slate-800 bg-slate-900 p-7">
            {cover?.download_url ? (
              <div
                aria-label={`封面：${cover.file_name}`}
                className="aspect-video rounded-2xl bg-cover bg-center"
                role="img"
                style={{ backgroundImage: `url(${cover.download_url})` }}
              />
            ) : (
              <div className="flex aspect-video items-center justify-center rounded-2xl border border-dashed border-slate-700 bg-slate-950 text-sm text-slate-500">
                暂无封面
              </div>
            )}
            <label className="block text-sm">标题
              <input className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3" onChange={(event) => setTitle(event.target.value)} value={title} />
            </label>
            <label className="block text-sm">文案
              <textarea className="mt-2 min-h-48 w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3" onChange={(event) => setBody(event.target.value)} value={body} />
            </label>
            <label className="block text-sm">上传运营截图
              <input accept="image/jpeg,image/png,image/webp" className="mt-2 block" onChange={upload} type="file" />
            </label>
            <div className="flex flex-wrap gap-3">
              <button className="rounded-xl bg-cyan-400 px-5 py-3 font-semibold text-slate-950" disabled={pending} onClick={() => mutate({ title, body }, "草稿已保存")} type="button">保存草稿</button>
              {!content.deleted_at && content.status === "draft" ? <button className="rounded-xl border border-emerald-500/50 px-5 py-3 text-emerald-300" disabled={pending} onClick={() => mutate({ status: "published" }, "已发布并冻结最终版本")} type="button">发布作品</button> : null}
              {content.deleted_at ? <button className="rounded-xl border border-cyan-500/50 px-5 py-3" disabled={pending} onClick={() => mutate({ restore: true }, "已从回收站恢复")} type="button">从回收站恢复</button> : <button className="rounded-xl border border-rose-500/50 px-5 py-3 text-rose-300" disabled={pending} onClick={remove} type="button">移入回收站</button>}
            </div>
            {message ? <p className="text-sm text-cyan-300">{message}</p> : null}
          </section>

          <aside className="space-y-4">
            <section className="rounded-3xl border border-slate-800 bg-slate-900 p-6"><h2 className="font-semibold">数据完整度</h2><p className="mt-2 text-sm text-slate-400">数据完整度待计算</p></section>
            <section className="rounded-3xl border border-slate-800 bg-slate-900 p-6"><h2 className="font-semibold">后续模块</h2><p className="mt-3 text-sm text-slate-400">数据诊断（即将开放）</p><p className="mt-2 text-sm text-slate-400">内容生成（即将开放）</p></section>
          </aside>
        </div>
      </div>
    </main>
  );
}
