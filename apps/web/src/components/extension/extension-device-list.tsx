"use client";

import { useCallback, useEffect, useRef, useState, type ReactElement } from "react";

import { DesktopOnlyNotice, ErrorState, Skeleton, StatusBadge } from "@/components/workbench/ui";
import { useWorkbenchShellContext } from "@/components/workbench/workspace-shell";
import {
  ExtensionDeviceApiError,
  listExtensionDevices,
  revokeExtensionDevice,
  type ExtensionDeviceRead,
} from "@/lib/extension-device-api";

type WorkspaceRole = "admin" | "editor" | "viewer";

function captureShortcut(): string {
  if (typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform)) {
    return "Command + Shift + 8";
  }
  return "Ctrl + Shift + 8";
}

function safeErrorMessage(failure: unknown, fallback: string): string {
  return failure instanceof ExtensionDeviceApiError ? failure.message : fallback;
}

function displayDate(value: string | null): string {
  if (!value) return "尚未记录";
  return new Date(value).toLocaleString("zh-CN");
}

function RevokeConfirmation({
  busy,
  error,
  onCancel,
  onConfirm,
}: {
  busy: boolean;
  error: string;
  onCancel: () => void;
  onConfirm: () => void;
}): ReactElement {
  return (
    <div
      aria-labelledby="extension-device-revoke-title"
      aria-modal="true"
      className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-950/45 p-4"
      role="dialog"
    >
      <section className="w-full max-w-md rounded-xl bg-white p-5 shadow-2xl">
        <h3 className="text-lg font-semibold" id="extension-device-revoke-title">
          确认撤销设备
        </h3>
        <p className="mt-2 text-sm text-[var(--text-secondary)]">
          撤销后，这台设备不能继续使用扩展连接；如需恢复，需由有权限的成员重新配对。
        </p>
        {error ? <p className="mt-3 text-sm text-red-800" role="alert">{error}</p> : null}
        <div className="mt-5 flex flex-wrap justify-end gap-3">
          <button className="rounded-lg border px-3 py-2 text-sm" disabled={busy} onClick={onCancel} type="button">
            取消
          </button>
          <button
            className="rounded-lg bg-red-700 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
            disabled={busy}
            onClick={onConfirm}
            type="button"
          >
            {error ? "重试撤销此设备" : "确认撤销"}
          </button>
        </div>
      </section>
    </div>
  );
}

export function ExtensionDeviceList({
  workspaceId,
  role: suppliedRole,
}: {
  workspaceId: string;
  role?: WorkspaceRole;
}): ReactElement {
  const context = useWorkbenchShellContext();
  const role = suppliedRole ?? context?.role ?? "viewer";
  const [devices, setDevices] = useState<ExtensionDeviceRead[]>([]);
  const [loading, setLoading] = useState(role === "admin");
  const [loadError, setLoadError] = useState("");
  const [confirmingDeviceId, setConfirmingDeviceId] = useState<string | null>(null);
  const [revoking, setRevoking] = useState(false);
  const [revokeError, setRevokeError] = useState("");
  const requestRef = useRef(0);
  const isAdmin = role === "admin";

  const loadDevices = useCallback(async () => {
    if (!isAdmin) return;
    const requestId = requestRef.current + 1;
    requestRef.current = requestId;
    setLoading(true);
    setLoadError("");
    try {
      const nextDevices = await listExtensionDevices(
        workspaceId,
        sessionStorage.getItem("workspace_csrf") ?? "",
      );
      if (requestId === requestRef.current) setDevices(nextDevices);
    } catch (failure) {
      if (requestId === requestRef.current) {
        setLoadError(safeErrorMessage(failure, "暂时无法加载设备，请稍后重试。"));
      }
    } finally {
      if (requestId === requestRef.current) setLoading(false);
    }
  }, [isAdmin, workspaceId]);

  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (active) void loadDevices();
    });
    return () => {
      active = false;
      requestRef.current += 1;
    };
  }, [loadDevices]);

  const revoke = useCallback(async () => {
    if (!confirmingDeviceId) return;
    setRevoking(true);
    setRevokeError("");
    try {
      await revokeExtensionDevice(
        workspaceId,
        confirmingDeviceId,
        sessionStorage.getItem("workspace_csrf") ?? "",
      );
      setDevices((current) => current.map((device) => (
        device.device_id === confirmingDeviceId
          ? { ...device, revoked_at: new Date().toISOString(), status: "revoked" }
          : device
      )));
      setConfirmingDeviceId(null);
    } catch (failure) {
      setRevokeError(safeErrorMessage(failure, "暂时无法撤销此设备，请稍后重试。"));
    } finally {
      setRevoking(false);
    }
  }, [confirmingDeviceId, workspaceId]);

  if (!isAdmin) {
    return (
      <section aria-labelledby="extension-connection-guidance" className="rounded-xl border bg-white p-5">
        <h2 className="font-semibold" id="extension-connection-guidance">浏览器扩展连接</h2>
        <p className="mt-2 text-sm text-[var(--text-secondary)]">保持连接，直到你或管理员解除</p>
        <p className="mt-2 text-sm text-[var(--text-secondary)]">
          当前角色只能查看连接说明，不能查看或撤销设备。需要处理设备时请联系管理员。
        </p>
      </section>
    );
  }

  return (
    <section aria-labelledby="extension-devices-heading" className="rounded-xl border bg-white p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold" id="extension-devices-heading">已连接的浏览器设备</h2>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">
            只显示设备名称、浏览器、扩展版本和使用时间；不会显示设备密钥、指纹或连接凭据。
          </p>
        </div>
        <p className="rounded-lg bg-slate-50 px-3 py-2 text-sm font-semibold">
          采集快捷键：<kbd>{captureShortcut()}</kbd>
        </p>
      </div>
      <div className="mt-4 md:hidden">
        <DesktopOnlyNotice
          action="管理已连接设备"
          description="设备撤销涉及持续连接状态；请在电脑端查看设备并完成撤销确认。"
        />
      </div>
      {loading ? <div className="mt-4"><Skeleton label="正在加载已连接设备" /></div> : null}
      {loadError ? (
        <div className="mt-4">
          <ErrorState
            description={loadError}
            retryAction={(
              <button className="rounded-lg border px-3 py-2 text-sm font-semibold" onClick={() => void loadDevices()} type="button">
                重试加载设备
              </button>
            )}
            title="无法加载设备"
          />
        </div>
      ) : null}
      {!loading && !loadError ? (
        <div className="mt-4 hidden space-y-3 md:block">
          {devices.length === 0 ? <p className="text-sm text-[var(--text-secondary)]">当前没有已连接设备。</p> : null}
          {devices.map((device) => (
            <article className="rounded-xl border p-4" key={device.device_id}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h3 className="font-semibold">{device.label}</h3>
                  <p className="mt-1 text-sm text-[var(--text-secondary)]">
                    {device.browser} · 扩展 {device.extension_version}
                  </p>
                  <p className="mt-1 text-sm text-[var(--text-secondary)]">
                    连接于 {displayDate(device.created_at)} · 最近使用 {displayDate(device.last_used_at)}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-3">
                  <StatusBadge tone={device.status === "active" ? "success" : "neutral"}>
                    {device.status === "active" ? "已连接" : "已撤销"}
                  </StatusBadge>
                  {device.status === "active" ? (
                    <button
                      className="rounded-lg border border-red-300 px-3 py-2 text-sm font-semibold text-red-800"
                      onClick={() => {
                        setRevokeError("");
                        setConfirmingDeviceId(device.device_id);
                      }}
                      type="button"
                    >
                      撤销此设备
                    </button>
                  ) : null}
                </div>
              </div>
            </article>
          ))}
        </div>
      ) : null}
      {confirmingDeviceId ? (
        <RevokeConfirmation
          busy={revoking}
          error={revokeError}
          onCancel={() => {
            if (!revoking) {
              setConfirmingDeviceId(null);
              setRevokeError("");
            }
          }}
          onConfirm={() => void revoke()}
        />
      ) : null}
    </section>
  );
}
