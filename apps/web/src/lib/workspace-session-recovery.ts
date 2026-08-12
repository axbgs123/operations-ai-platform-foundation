const RECOVERY_KEY = "operations-ai:workspace-session-recovery:v1";
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const CSRF_PATTERN = /^[A-Za-z0-9_-]{16,512}$/;

export type WorkspaceSessionRecoveryRecord = {
  version: 1;
  workspaceId: string;
  memberId: string;
  csrfToken: string;
};

function removeRecoveryKey(storage: Storage): void {
  try {
    storage.removeItem(RECOVERY_KEY);
  } catch {
    // A disabled browser storage backend already behaves like no recovery state.
  }
}

function isRecoveryRecord(value: unknown): value is WorkspaceSessionRecoveryRecord {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  const record = value as Record<string, unknown>;
  const keys = Object.keys(record).sort();
  if (
    keys.length !== 4
    || keys[0] !== "csrfToken"
    || keys[1] !== "memberId"
    || keys[2] !== "version"
    || keys[3] !== "workspaceId"
  ) {
    return false;
  }
  return record.version === 1
    && typeof record.workspaceId === "string"
    && UUID_PATTERN.test(record.workspaceId)
    && typeof record.memberId === "string"
    && UUID_PATTERN.test(record.memberId)
    && typeof record.csrfToken === "string"
    && CSRF_PATTERN.test(record.csrfToken);
}

export function readWorkspaceSessionRecovery(
  storage: Storage,
): WorkspaceSessionRecoveryRecord | null {
  let raw: string | null;
  try {
    raw = storage.getItem(RECOVERY_KEY);
  } catch {
    return null;
  }
  if (raw === null) return null;

  try {
    const parsed: unknown = JSON.parse(raw);
    if (isRecoveryRecord(parsed)) return parsed;
  } catch {
    // Invalid JSON is handled by removing only the recovery key below.
  }
  removeRecoveryKey(storage);
  return null;
}

export function writeWorkspaceSessionRecovery(
  storage: Storage,
  record: Omit<WorkspaceSessionRecoveryRecord, "version">,
): void {
  const versioned: WorkspaceSessionRecoveryRecord = { version: 1, ...record };
  if (!isRecoveryRecord(versioned)) {
    removeRecoveryKey(storage);
    return;
  }
  try {
    storage.setItem(RECOVERY_KEY, JSON.stringify(versioned));
  } catch {
    removeRecoveryKey(storage);
  }
}

export function clearWorkspaceSessionRecovery(storage: Storage): void {
  removeRecoveryKey(storage);
}

export function restoreWorkspaceCsrf(
  storage: Storage,
  record: WorkspaceSessionRecoveryRecord,
): void {
  storage.setItem("workspace_csrf", record.csrfToken);
}
