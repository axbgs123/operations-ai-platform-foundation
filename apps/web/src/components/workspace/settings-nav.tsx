import Link from "next/link";

export const SETTINGS_ITEMS = [
  { label: "工作区概览", href: "/settings" },
  { label: "成员与邀请码", href: "/settings/members" },
  { label: "平台账号", href: "/accounts" },
  { label: "AI 模型连接", href: "/settings/models" },
  { label: "公开数据采集", href: "/settings/public-data" },
] as const;

export function SettingsNav({ workspaceId }: { workspaceId: string }) {
  return (
    <nav
      aria-label="工作区设置"
      className="flex gap-2 overflow-x-auto rounded-xl border border-[var(--border)] bg-white p-2"
    >
      {SETTINGS_ITEMS.map((item) => (
        <Link
          className="shrink-0 rounded-lg px-3 py-2 text-sm font-medium text-[var(--text-secondary)] hover:bg-slate-100 hover:text-[var(--text-primary)]"
          href={`/workspaces/${workspaceId}${item.href}`}
          key={item.label}
        >
          {item.label}
        </Link>
      ))}
    </nav>
  );
}
