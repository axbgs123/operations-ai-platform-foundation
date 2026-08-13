"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import { confirmHotspotCapture, loadHotspotCapture, type HotspotCapture } from "@/lib/hotspot-api";
import { EmptyState, ErrorState, PageHeader, Panel, Skeleton } from "@/components/workbench/ui";
import { useWorkbenchShellContext } from "@/components/workbench/workspace-shell";

export function HotspotReview({ workspaceId }: { workspaceId: string }) {
  const captureId = useSearchParams().get("capture_id");
  const context = useWorkbenchShellContext();
  const [capture, setCapture] = useState<HotspotCapture>();
  const [failed, setFailed] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!captureId) return;
    loadHotspotCapture(workspaceId, captureId).then(setCapture).catch(() => setFailed(true));
  }, [captureId, workspaceId]);

  if (!captureId) return <EmptyState title="还没有待确认的热点截图" description="打开浏览器扩展，在任意公开 HTTPS 热点榜页面选择目标平台并采集。" />;
  if (failed) return <ErrorState title="无法读取这次热点截图" description="请确认连接的是同一个工作区，或重新采集。" />;
  if (!capture) return <Skeleton label="正在读取热点识别结果" />;

  const editable = context?.role === "admin" || context?.role === "editor";
  return <div className="space-y-5">
    <PageHeader title="确认热点截图" description="检查图片识别出的热点；只有确认后，智能体才可以引用这些内容。" />
    <Panel title="采集来源">
      <p>{capture.page_title}</p>
      <p className="text-sm text-[var(--text-secondary)]">目标平台：{capture.target_platform === "douyin" ? "抖音" : "小红书"} · 完整度：{capture.completeness}</p>
    </Panel>
    <Panel title="识别到的热点">
      {capture.candidates.length === 0 ? <p>没有识别到可用热点，请重新截图。</p> : <ol className="space-y-2">
        {capture.candidates.map((entry) => <li key={`${entry.position}-${entry.topic}`} className="rounded-lg border border-[var(--border)] p-3">
          <strong>{entry.rank ? `${entry.rank}. ` : ""}{entry.topic}</strong>{entry.heat ? <span className="ml-2 text-sm text-[var(--text-secondary)]">{entry.heat}</span> : null}
        </li>)}
      </ol>}
      {editable && capture.status === "review_ready" ? <button className="mt-4 rounded-lg bg-[var(--brand)] px-4 py-2 text-white" onClick={() => void confirmHotspotCapture(
        workspaceId, capture.id, capture.candidates, sessionStorage.getItem("workspace_csrf") ?? "",
      ).then(() => setSaved(true)).catch(() => setFailed(true))}>确认并保存</button> : null}
      {saved || capture.status === "confirmed" ? <p className="mt-3 text-sm">已保存，运营智能体现在可以使用这批热点。</p> : null}
    </Panel>
  </div>;
}
