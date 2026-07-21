export function DemoBanner() {
  return (
    <aside className="rounded-2xl border border-amber-300/30 bg-amber-300/10 px-5 py-4 text-amber-100">
      <p className="font-semibold">公开体验区</p>
      <p className="mt-1 text-sm text-amber-100/75">
        页面内容均为示例数据，生成结果来自 Mock 模型，不会写入真实工作区。
      </p>
    </aside>
  );
}
