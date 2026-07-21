import type { components } from "@operations-ai/shared-schemas";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type ContentAssetData = components["schemas"]["AssetRead"];
export type ContentData = components["schemas"]["ContentRead"];
type AssetUploadGrant = components["schemas"]["AssetUploadGrantRead"];
type AssetPresignRequest = components["schemas"]["AssetPresignRequest"];
type ContentCreate = components["schemas"]["ContentCreate"];
type ContentUpdate = components["schemas"]["ContentUpdate"];

async function contentRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? "作品请求失败");
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function loadContent(contentId: string) {
  return contentRequest<ContentData>(`/v1/contents/${contentId}`);
}

export function createContent(data: ContentCreate, csrfToken: string) {
  return contentRequest<ContentData>("/v1/contents", {
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
    body: JSON.stringify(data),
  });
}

export function updateContent(contentId: string, data: ContentUpdate, csrfToken: string) {
  return contentRequest<ContentData>(`/v1/contents/${contentId}`, {
    method: "PATCH",
    headers: { "X-CSRF-Token": csrfToken },
    body: JSON.stringify(data),
  });
}

export function deleteContent(contentId: string, csrfToken: string) {
  return contentRequest<void>(`/v1/contents/${contentId}`, {
    method: "DELETE",
    headers: { "X-CSRF-Token": csrfToken },
  });
}

export async function uploadContentAsset(
  contentId: string,
  file: File,
  category: AssetPresignRequest["category"],
  csrfToken: string,
) {
  const grant = await contentRequest<AssetUploadGrant>(`/v1/contents/${contentId}/assets/presign`, {
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
    body: JSON.stringify({
      category,
      file_name: file.name,
      mime_type: file.type,
      size: file.size,
    }),
  });
  const uploaded = await fetch(grant.upload_url, {
    method: "PUT",
    headers: grant.upload_headers,
    body: file,
  });
  if (!uploaded.ok) throw new Error("素材上传失败，未写入作品记录");
  return contentRequest<ContentAssetData>(`/v1/contents/${contentId}/assets/confirm`, {
    method: "POST",
    headers: { "X-CSRF-Token": csrfToken },
    body: JSON.stringify({ upload_token: grant.upload_token }),
  });
}
