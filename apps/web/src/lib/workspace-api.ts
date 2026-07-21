const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type SessionCreated = {
  workspace_id: string;
  member_id: string;
  csrf_token: string;
};

type MemberCodeCreated = {
  code: string;
  role: "admin" | "editor" | "viewer";
};

async function request<T>(path: string, init: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...init.headers },
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      detail?: string;
    } | null;
    throw new Error(payload?.detail ?? "请求失败，请稍后重试");
  }
  return response.json() as Promise<T>;
}

export function enterWorkspace(code: string, displayName: string) {
  return request<SessionCreated>("/v1/sessions/invite", {
    method: "POST",
    body: JSON.stringify({ code, display_name: displayName }),
  });
}

export function createMemberCode(
  workspaceId: string,
  role: "admin" | "editor" | "viewer",
  csrfToken: string,
) {
  return request<MemberCodeCreated>(
    `/v1/workspaces/${workspaceId}/members/codes`,
    {
      method: "POST",
      body: JSON.stringify({ role }),
      headers: { "X-CSRF-Token": csrfToken },
    },
  );
}
