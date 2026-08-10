"use client";

import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactElement,
} from "react";
import { createPortal } from "react-dom";

import {
  createExtensionPairingCode,
  ExtensionPairingApiError,
  type ExtensionPairingCodeRead,
} from "@/lib/extension-pairing-api";

type WorkspaceRole = "admin" | "editor" | "viewer";

const FOCUSABLE = [
  "button:not([disabled])",
  "[href]",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

function remainingLabel(expiresAt: string, now: number): string {
  const remainingMs = new Date(expiresAt).getTime() - now;
  if (remainingMs <= 0) return "连接码已过期";
  return `${Math.ceil(remainingMs / 60_000)} 分钟内有效`;
}

export function ExtensionPairingPanel({
  workspaceId,
  role,
  triggerLabel,
}: {
  workspaceId: string;
  role: WorkspaceRole;
  triggerLabel: string;
}): ReactElement {
  const [open, setOpen] = useState(false);
  const [pairing, setPairing] = useState<ExtensionPairingCodeRead | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const triggerRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const pairingCodeRef = useRef("");
  const pairingRequestRef = useRef(0);
  const writable = role === "admin" || role === "editor";

  function clearPlaintext() {
    pairingCodeRef.current = "";
    setPairing(null);
  }

  function closeDialog() {
    pairingRequestRef.current += 1;
    clearPlaintext();
    setError("");
    setBusy(false);
    setOpen(false);
    triggerRef.current?.focus();
  }

  useEffect(() => () => {
    pairingRequestRef.current += 1;
    pairingCodeRef.current = "";
  }, []);

  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!pairing) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [pairing]);

  async function generateCode() {
    const requestId = pairingRequestRef.current + 1;
    pairingRequestRef.current = requestId;
    clearPlaintext();
    setError("");
    setBusy(true);
    try {
      const nextPairing = await createExtensionPairingCode(
        workspaceId,
        sessionStorage.getItem("workspace_csrf") ?? "",
      );
      if (requestId !== pairingRequestRef.current) return;
      pairingCodeRef.current = nextPairing.pairing_code;
      setNow(Date.now());
      setPairing(nextPairing);
    } catch (failure) {
      if (requestId !== pairingRequestRef.current) return;
      setError(
        failure instanceof ExtensionPairingApiError
          ? failure.message
          : "暂时无法生成连接码，请稍后重试。",
      );
    } finally {
      if (requestId === pairingRequestRef.current) setBusy(false);
    }
  }

  async function copyCode() {
    if (!pairing) return;
    try {
      await window.navigator.clipboard.writeText(pairing.pairing_code);
    } catch {
      setError("无法复制连接码，请手动复制后重试。");
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      closeDialog();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = Array.from(
      dialogRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [],
    );
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  if (!writable) {
    return (
      <div className="space-y-1 text-sm text-[var(--text-secondary)]">
        <p>查看者只能查看扩展连接说明。请联系管理员或编辑者生成连接码。</p>
        <p>保持连接，直到你或管理员解除</p>
      </div>
    );
  }

  return (
    <>
      <button
        className="rounded-lg border border-violet-200 bg-violet-50 px-3 py-2 text-sm font-semibold text-[var(--brand)] hover:bg-violet-100"
        onClick={() => setOpen(true)}
        ref={triggerRef}
        type="button"
      >
        {triggerLabel}
      </button>
      {open ? createPortal(
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-950/45 p-4">
          <div
            aria-describedby="extension-pairing-steps"
            aria-labelledby="extension-pairing-title"
            aria-modal="true"
            className="w-full max-w-lg rounded-xl bg-white p-5 shadow-2xl"
            onKeyDown={handleKeyDown}
            ref={dialogRef}
            role="dialog"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-lg font-semibold" id="extension-pairing-title">
                  连接浏览器扩展
                </h2>
                <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm text-[var(--text-secondary)]" id="extension-pairing-steps">
                  <li>生成一次性连接码。</li>
                  <li>在扩展的连接页面粘贴连接码。</li>
                  <li>确认扩展显示相同工作区后再开始采集。</li>
                </ol>
              </div>
              <button
                aria-label="关闭"
                className="h-10 w-10 shrink-0 rounded-lg border text-xl"
                onClick={closeDialog}
                ref={closeRef}
                type="button"
              >
                ×
              </button>
            </div>
            <p className="mt-4 text-sm text-[var(--text-secondary)]">
              当前便携式默认本地服务地址：<code>http://127.0.0.1:51201</code>（不是通用生产地址）。
            </p>
            <p className="mt-2 text-sm text-[var(--text-secondary)]">
              保持连接，直到你或管理员解除
            </p>
            <p className="mt-2 text-sm text-[var(--text-secondary)]">
              连接码仅 5 分钟有效；连接后的短期访问凭据每 8 小时自动续期。浏览器数据或设备密钥丢失时，请重新配对。
            </p>
            {error ? <p className="mt-4 text-sm text-red-700" role="alert">{error}</p> : null}
            {pairing ? (
              <div className="mt-4 rounded-lg border bg-slate-50 p-4">
                <output aria-live="polite" className="block font-mono text-2xl font-semibold tracking-widest">
                  {pairing.pairing_code}
                </output>
                <p className="mt-2 text-sm text-[var(--text-secondary)]">
                  {remainingLabel(pairing.expires_at, now)}
                </p>
              </div>
            ) : null}
            <div className="mt-5 flex flex-wrap gap-3">
              {!pairing ? (
                <button
                  className="rounded-lg bg-[var(--brand)] px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
                  disabled={busy}
                  onClick={generateCode}
                  type="button"
                >
                  生成连接码
                </button>
              ) : (
                <>
                  <button
                    className="rounded-lg border px-3 py-2 text-sm font-semibold"
                    onClick={copyCode}
                    type="button"
                  >
                    复制连接码
                  </button>
                  <button
                    className="rounded-lg border px-3 py-2 text-sm font-semibold disabled:opacity-50"
                    disabled={busy}
                    onClick={generateCode}
                    type="button"
                  >
                    重新生成
                  </button>
                </>
              )}
              <button
                className="rounded-lg border px-3 py-2 text-sm"
                onClick={closeDialog}
                type="button"
              >
                关闭
              </button>
            </div>
          </div>
        </div>,
        document.body,
      ) : null}
    </>
  );
}
