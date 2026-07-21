import type { components } from "@operations-ai/shared-schemas";

import type { DemoWorkspaceData } from "@/components/demo-workspace";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type DemoGenerateRequest = components["schemas"]["DemoGenerateRequest"];
type DemoGenerateResponse = components["schemas"]["DemoGenerateResponse"];
type DemoSessionCreated = components["schemas"]["DemoSessionCreated"];

async function demoRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? "公开体验区暂时不可用");
  }
  return response.json() as Promise<T>;
}

export function loadDemoWorkspace() {
  return demoRequest<DemoWorkspaceData>("/v1/demo/workspace");
}

export function createDemoSession() {
  return demoRequest<DemoSessionCreated>("/v1/demo/sessions", {
    method: "POST",
  });
}

export function generateDemoTitle(prompt: string) {
  const payload: DemoGenerateRequest = { prompt };
  return demoRequest<DemoGenerateResponse>("/v1/demo/generations", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
