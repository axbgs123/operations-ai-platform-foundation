"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import {
  confirmHotspotCapture,
  loadHotspotCapture,
  loadHotspotResearch,
  loadHotspotSnapshots,
  researchHotspot,
  saveHotspotCandidate,
  type HotspotCapture,
  type HotspotResearch,
  type HotspotSnapshot,
} from "@/lib/hotspot-api";
import {
  EmptyState,
  ErrorState,
  Panel,
  Skeleton,
} from "@/components/workbench/ui";
import { GuidedPageHeader } from "@/components/workbench/guided-page-header";
import { useWorkbenchShellContext } from "@/components/workbench/workspace-shell";

const csrf = () => sessionStorage.getItem("workspace_csrf") ?? "";

export function HotspotReview({ workspaceId }: { workspaceId: string }) {
  const captureId = useSearchParams().get("capture_id");
  const context = useWorkbenchShellContext();
  const [capture, setCapture] = useState<HotspotCapture>();
  const [snapshots, setSnapshots] = useState<HotspotSnapshot[]>([]);
  const [snapshotId, setSnapshotId] = useState("");
  const [accountId, setAccountId] = useState("");
  const [research, setResearch] = useState<HotspotResearch>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refreshSnapshots = useCallback(() => loadHotspotSnapshots(workspaceId).then((items) => {
    setSnapshots(items);
    setSnapshotId((current) => current || items[0]?.id || "");
  }), [workspaceId]);

  useEffect(() => {
    void refreshSnapshots().catch(() => setError("热点记录读取失败，请刷新页面。"));
    void loadHotspotResearch(workspaceId)
      .then((items) => setResearch(items.find((item) => item.status === "succeeded")))
      .catch(() => setError("热点研究记录读取失败，请刷新页面。"));
    if (captureId) {
      void loadHotspotCapture(workspaceId, captureId)
        .then(setCapture)
        .catch(() => setError("无法读取这次热点截图，请确认连接的是同一个工作区。"));
    }
  }, [captureId, refreshSnapshots, workspaceId]);

  if (!context) return <Skeleton label="正在读取热点创作工作区" />;
  const editable = context.role === "admin" || context.role === "editor";
  const selectedSnapshot = snapshots.find((item) => item.id === snapshotId);
  const accounts = context.accounts.filter(
    (item) => !selectedSnapshot || item.platform === selectedSnapshot.target_platform,
  );
  const effectiveAccountId = accountId || accounts[0]?.account_id || "";

  const confirm = async () => {
    if (!capture) return;
    setBusy(true); setError("");
    try {
      const saved = await confirmHotspotCapture(workspaceId, capture.id, capture.candidates, csrf());
      setSnapshotId(saved.id);
      setCapture({ ...capture, status: "confirmed", confirmed_snapshot_id: saved.id });
      await refreshSnapshots();
    } catch { setError("热点确认失败，请检查识别内容后重试。"); }
    finally { setBusy(false); }
  };

  const startResearch = async () => {
    if (!snapshotId || !effectiveAccountId) return;
    setBusy(true); setError("");
    try { setResearch(await researchHotspot(workspaceId, snapshotId, effectiveAccountId, csrf())); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "联网核实失败"); }
    finally { setBusy(false); }
  };

  const saveCandidate = async (index: number) => {
    if (!research) return;
    setBusy(true); setError("");
    try { setResearch(await saveHotspotCandidate(workspaceId, research.id, index, csrf())); }
    catch { setError("保存内容草稿失败，请确认账号已经配置目标和基准。"); }
    finally { setBusy(false); }
  };

  return <div className="space-y-5">
    <GuidedPageHeader pageId="hotspots" />
    {error ? <ErrorState title="当前操作没有完成" description={error} /> : null}

    {capture ? <Panel title="第一步：确认截图识别结果">
      <p className="font-medium">{capture.page_title}</p>
      <p className="text-sm text-[var(--text-secondary)]">
        目标平台：{capture.target_platform === "douyin" ? "抖音" : "小红书"} · {capture.completeness}
      </p>
      {capture.candidates.length === 0 ? <p className="mt-3">没有识别到热点，请重新截图。</p> : <ol className="mt-3 space-y-2">
        {capture.candidates.map((entry) => <li key={`${entry.position}-${entry.topic}`} className="rounded-lg border border-[var(--border)] p-3">
          <strong>{entry.rank ? `${entry.rank}. ` : ""}{entry.topic}</strong>
          {entry.heat ? <span className="ml-2 text-sm text-[var(--text-secondary)]">{entry.heat}</span> : null}
        </li>)}
      </ol>}
      {editable && capture.status === "review_ready" ? <button disabled={busy} className="mt-4 rounded-lg bg-[var(--brand)] px-4 py-2 text-white disabled:opacity-50" onClick={() => void confirm()}>
        {busy ? "正在保存…" : "确认这些热点"}
      </button> : null}
      {capture.status === "confirmed" ? <p className="mt-3">已确认，可以进入下一步。</p> : null}
    </Panel> : null}

    <Panel title="第二步：选择热点和账号">
      {snapshots.length === 0 ? <EmptyState title="还没有已确认热点" description="打开浏览器扩展，在公开 HTTPS 热点榜页面选择目标平台并采集。" /> : <div className="grid gap-4 md:grid-cols-2">
        <label className="text-sm">热点记录
          <select className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] p-2" value={snapshotId} onChange={(event) => { setSnapshotId(event.target.value); setAccountId(""); setResearch(undefined); }}>
            {snapshots.map((item) => <option key={item.id} value={item.id}>{item.page_title}（{item.entries.length} 条）</option>)}
          </select>
        </label>
        <label className="text-sm">用于哪个账号
          <select className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] p-2" value={effectiveAccountId} onChange={(event) => setAccountId(event.target.value)}>
            <option value="">请选择同平台账号</option>
            {accounts.map((item) => <option key={item.account_id} value={item.account_id}>{item.name}</option>)}
          </select>
        </label>
      </div>}
      {editable && snapshots.length > 0 ? <button disabled={busy || !effectiveAccountId} className="mt-4 rounded-lg bg-[var(--brand)] px-4 py-2 text-white disabled:opacity-50" onClick={() => void startResearch()}>
        {busy ? "正在联网核实…" : "联网核实并生成草稿"}
      </button> : null}
      <p className="mt-2 text-sm text-[var(--text-secondary)]">仅使用已通过连接检测的模型原生联网能力；没有真实 HTTPS 引用时不会生成成功结果。</p>
    </Panel>

    {research ? <Panel title="第三步：检查研究与创作候选">
      <p>{research.summary}</p>
      <ul className="mt-3 list-disc space-y-1 pl-5">{research.key_points.map((point) => <li key={point}>{point}</li>)}</ul>
      <div className="mt-4 space-y-4">{research.candidates.map((candidate, index) => <article key={`${candidate.topic}-${index}`} className="rounded-lg border border-[var(--border)] p-4">
        <h3 className="font-semibold">{candidate.topic}</h3>
        <p className="mt-2">切入角度：{candidate.angle}</p>
        <p className="mt-2">账号匹配：{candidate.account_fit}</p>
        <p className="mt-2 font-medium">标题候选</p>
        <ul className="list-disc pl-5">{candidate.titles.map((title) => <li key={title}>{title}</li>)}</ul>
        <p className="mt-2 whitespace-pre-wrap">{candidate.copy_draft}</p>
        <p className="mt-2 text-sm font-medium">引用来源</p>
        <ul>{candidate.source_urls.map((url) => <li key={url}><a className="text-[var(--brand)] underline" href={url} target="_blank" rel="noreferrer">{url}</a></li>)}</ul>
        {editable && !research.saved_content_id ? <button disabled={busy} className="mt-3 rounded-lg border border-[var(--brand)] px-3 py-2 text-[var(--brand)]" onClick={() => void saveCandidate(index)}>保存为内容草稿</button> : null}
      </article>)}</div>
      {research.saved_content_id ? <p className="mt-4"><Link className="text-[var(--brand)] underline" href={`/workspaces/${workspaceId}/contents/${research.saved_content_id}`}>已保存，前往内容详情继续事实核验和发布前检查</Link></p> : null}
      <p className="mt-4 text-sm text-[var(--text-secondary)]">联网结果和生成内容仍需人工核实；保存不等于发布，平台风控以发布前检查为准。</p>
    </Panel> : null}
  </div>;
}
