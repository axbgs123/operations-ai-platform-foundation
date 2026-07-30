export function DemoBanner() {
  return (
    <aside className="rounded-xl border border-blue-200 bg-blue-50 px-5 py-4 text-blue-950">
      <p className="font-semibold">示例工作区 · 只读</p>
      <p className="mt-1 text-sm text-blue-800">
        页面内容均为示例/Mock 数据，生成结果来自 Mock 模型，不会写入真实工作区。Mock 不等于生产模型效果。
      </p>
    </aside>
  );
}
