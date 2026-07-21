"use client";

import { useEffect, useState } from "react";

import { ContentDetail } from "@/components/content/content-detail";
import { ContentData, loadContent } from "@/lib/content-api";


export function ContentLoader({ contentId }: { contentId: string }) {
  const [content, setContent] = useState<ContentData>();
  const [error, setError] = useState("");
  useEffect(() => {
    loadContent(contentId).then(setContent).catch((caught) => setError(caught instanceof Error ? caught.message : "加载失败"));
  }, [contentId]);
  if (error) return <main className="p-10 text-rose-400">{error}</main>;
  if (!content) return <main className="p-10 text-slate-400">正在加载作品…</main>;
  return <ContentDetail initialContent={content} />;
}
