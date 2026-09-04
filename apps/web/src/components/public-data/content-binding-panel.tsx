"use client";

import { FormEvent, useEffect, useState } from "react";

import {
  collectPublicContentNow,
  getPublicContentBinding,
  savePublicContentBinding,
  type PublicContentBinding,
} from "@/lib/public-data-api";
import { Panel, StatusBadge } from "@/components/workbench/ui";

const jobLabel: Record<string, string> = {
  "1h": "发布后 1 小时",
  "24h": "发布后 24 小时",
  "72h": "发布后 3 天",
  "7d": "发布后 7 天",
};

const jobStatus: Record<string, string> = {
  scheduled: "等待采集",
  running: "正在采集",
  retrying: "稍后重试",
  succeeded: "已采集",
  failed: "采集失败",
  cancelled: "已取消",
};

function toLocalInput(value: string | null): string {
  const date = value ? new Date(value) : new Date();
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

export function PublicDataBindingPanel({
  workspaceId,
  contentId,
  role,
  initialUrl,
  initialPublishedAt,
}: {
  workspaceId: string;
  contentId: string;
  role: "admin" | "editor" | "viewer";
  initialUrl: string | null;
  initialPublishedAt: string | null;
}) {
  const [binding, setBinding] = useState<PublicContentBinding | null>(null);
  const [publicUrl, setPublicUrl] = useState(initialUrl ?? "");
  const [publishedAt, setPublishedAt] = useState(toLocalInput(initialPublishedAt));
  const [platformContentId, setPlatformContentId] = useState("");
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    let active = true;
    getPublicContentBinding(workspaceId, contentId)
      .then((value) => {
        if (!active || !value) return;
        setBinding(value);
        setPublicUrl(value.public_url);
        setPublishedAt(toLocalInput(value.published_at));
        setPlatformContentId(value.platform_content_id);
      })
      .catch((error) => {
        if (active) setMessage(error instanceof Error ? error.message : "采集计划加载失败");
      });
    return () => {
      active = false;
    };
  }, [contentId, workspaceId]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setMessage("");
    try {
      const saved = await savePublicContentBinding(
        workspaceId,
        contentId,
        sessionStorage.getItem("workspace_csrf") ?? "",
        {
          public_url: publicUrl,
          published_at: new Date(publishedAt).toISOString(),
          platform_content_id: platformContentId.trim() || null,
        },
      );
      setBinding(saved);
      setPlatformContentId(saved.platform_content_id);
      setMessage("作品已绑定，自动采集计划已经建立。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "绑定失败");
    } finally {
      setPending(false);
    }
  }

  async function collectNow() {
    setPending(true);
    setMessage("");
    try {
      const job = await collectPublicContentNow(
        workspaceId,
        contentId,
        sessionStorage.getItem("workspace_csrf") ?? "",
      );
      setBinding((current) => current
        ? { ...current, jobs: [...current.jobs, job] }
        : current);
      setMessage("已开始采集，完成后刷新页面即可看到新快照。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "采集启动失败");
    } finally {
      setPending(false);
    }
  }

  return (
    <Panel
      description="粘贴已发布作品的公开链接，系统会自动回收点赞、评论、收藏、分享等公开数据。"
      title="公开作品自动采集"
    >
      {role === "viewer" ? (
        binding ? (
          <a className="text-sm font-semibold text-[var(--brand)] underline" href={binding.public_url}>
            打开已绑定作品
          </a>
        ) : <p className="text-sm">尚未绑定公开作品。</p>
      ) : (
        <form className="space-y-4" onSubmit={save}>
          <label className="block text-sm font-medium">
            作品公开链接
            <input
              className="mt-2 w-full rounded-xl border border-[var(--border)] bg-white px-4 py-3"
              onChange={(event) => setPublicUrl(event.target.value)}
              placeholder="粘贴抖音或小红书作品链接"
              required
              type="url"
              value={publicUrl}
            />
          </label>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block text-sm font-medium">
              发布时间
              <input
                className="mt-2 w-full rounded-xl border border-[var(--border)] bg-white px-4 py-3"
                onChange={(event) => setPublishedAt(event.target.value)}
                required
                type="datetime-local"
                value={publishedAt}
              />
            </label>
            <label className="block text-sm font-medium">
              平台作品 ID（选填）
              <input
                className="mt-2 w-full rounded-xl border border-[var(--border)] bg-white px-4 py-3"
                onChange={(event) => setPlatformContentId(event.target.value)}
                placeholder="无法自动识别时再填写"
                value={platformContentId}
              />
            </label>
          </div>
          <div className="flex flex-wrap gap-3">
            <button
              className="rounded-lg bg-[var(--brand)] px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
              disabled={pending}
              type="submit"
            >
              {binding ? "更新作品与计划" : "绑定作品并开始计划"}
            </button>
            <button
              className="rounded-lg border border-[var(--border)] bg-white px-4 py-2.5 text-sm font-semibold disabled:opacity-50"
              disabled={pending || !binding}
              onClick={collectNow}
              type="button"
            >
              立即采集一次
            </button>
          </div>
        </form>
      )}
      {binding?.jobs.length ? (
        <ul className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {binding.jobs.filter((job) => !job.target_window.startsWith("manual-")).map((job) => (
            <li className="rounded-lg bg-slate-50 p-3 text-sm" key={job.id}>
              <p className="font-semibold">
                {jobLabel[job.target_window] ?? "补采任务"}
              </p>
              <div className="mt-2">
                <StatusBadge tone={job.status === "succeeded" ? "success" : job.status === "failed" ? "danger" : "info"}>
                  {jobStatus[job.status] ?? job.status}
                </StatusBadge>
              </div>
            </li>
          ))}
        </ul>
      ) : null}
      {message ? <p className="mt-4 text-sm" role="status">{message}</p> : null}
    </Panel>
  );
}
