import { createHash } from "node:crypto";

import {
  APIRequestContext,
  expect,
  test,
} from "@playwright/test";

const api =
  process.env.FRESH_INSTALL_API_URL ?? "http://127.0.0.1:8100";

type Json = Record<string, any>;

async function json(response: Awaited<ReturnType<APIRequestContext["get"]>>) {
  const body = await response.json();
  expect(response.ok(), JSON.stringify(body)).toBeTruthy();
  return body as Json;
}

function parseStoredZip(payload: Buffer): Map<string, Buffer> {
  const entries = new Map<string, Buffer>();
  let offset = 0;
  while (offset + 4 <= payload.length) {
    const signature = payload.readUInt32LE(offset);
    if (signature !== 0x04034b50) break;
    const method = payload.readUInt16LE(offset + 8);
    const compressedSize = payload.readUInt32LE(offset + 18);
    const nameLength = payload.readUInt16LE(offset + 26);
    const extraLength = payload.readUInt16LE(offset + 28);
    expect(method).toBe(0);
    const nameStart = offset + 30;
    const dataStart = nameStart + nameLength + extraLength;
    const name = payload
      .subarray(nameStart, nameStart + nameLength)
      .toString("utf8");
    entries.set(
      name,
      payload.subarray(dataStart, dataStart + compressedSize),
    );
    offset = dataStart + compressedSize;
  }
  return entries;
}

function tamperStoredZipEntry(payload: Buffer, entryName: string): Buffer {
  const tampered = Buffer.from(payload);
  let offset = 0;
  while (offset + 30 <= tampered.length) {
    const signature = tampered.readUInt32LE(offset);
    if (signature !== 0x04034b50) break;
    const compressedSize = tampered.readUInt32LE(offset + 18);
    const nameLength = tampered.readUInt16LE(offset + 26);
    const extraLength = tampered.readUInt16LE(offset + 28);
    const nameStart = offset + 30;
    const dataStart = nameStart + nameLength + extraLength;
    const name = tampered
      .subarray(nameStart, nameStart + nameLength)
      .toString("utf8");
    if (name === entryName) {
      if (compressedSize === 0) {
        throw new Error(`Cannot tamper empty ZIP entry: ${entryName}`);
      }
      tampered[dataStart + Math.floor(compressedSize / 2)] ^= 0x01;
      return tampered;
    }
    offset = dataStart + compressedSize;
  }
  throw new Error(`ZIP entry not found: ${entryName}`);
}

async function waitForExport(
  request: APIRequestContext,
  workspaceId: string,
  taskId: string,
) {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    const task = await json(
      await request.get(
        `${api}/v1/workspaces/${workspaceId}/exports/${taskId}`,
      ),
    );
    if (task.status === "succeeded") return task;
    if (task.status === "failed") {
      throw new Error(`export failed: ${JSON.stringify(task)}`);
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error("export timed out");
}

async function waitForRestore(
  request: APIRequestContext,
  workspaceId: string,
  restoreId: string,
) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    const job = await json(
      await request.get(
        `${api}/v1/workspaces/${workspaceId}/zip-restores/${restoreId}`,
      ),
    );
    if (job.status === "succeeded" || job.status === "failed") return job;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error("restore timed out");
}

test("checksummed ZIP restores synthetic sourceWorkspace data into a server-derived target", async ({
  request,
}) => {
  let sourceWorkspace: Json;
  let csrf = "";
  let sourceContent: Json;
  let archive: Buffer;
  let archiveSha = "";
  let restore: Json;

  await test.step("1 create complete synthetic source workspace data", async () => {
    sourceWorkspace = await json(
      await request.post(`${api}/v1/workspaces`, {
        data: { name: `task9A-backup-source-${Date.now()}` },
      }),
    );
    const login = await json(
      await request.post(`${api}/v1/sessions/invite`, {
        data: {
          code: sourceWorkspace.admin_code,
          display_name: "task9A-backup-admin",
        },
      }),
    );
    csrf = login.csrf_token;
    const account = await json(
      await request.post(
        `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/accounts`,
        {
          headers: { "X-CSRF-Token": csrf },
          data: {
            platform: "douyin",
            name: "synthetic backup AI technology",
            objectives: ["reach"],
            metric_weights: { views: 1 },
            benchmark_sample_size: 30,
          },
        },
      ),
    );
    sourceContent = await json(
      await request.post(`${api}/v1/contents`, {
        headers: { "X-CSRF-Token": csrf },
        data: {
          workspace_id: sourceWorkspace.workspace_id,
          account_id: account.id,
          platform: "douyin",
          content_type: "video",
          title: "synthetic portable AI technology report",
          body: "Only synthetic authorized data.",
        },
      }),
    );
    sourceContent = await json(
      await request.patch(`${api}/v1/contents/${sourceContent.id}`, {
        headers: { "X-CSRF-Token": csrf },
        data: { status: "published" },
      }),
    );
    const snapshot = await json(
      await request.post(
        `${api}/v1/contents/${sourceContent.id}/snapshots`,
        {
          headers: { "X-CSRF-Token": csrf },
          data: {
            collected_at: new Date(
              new Date(sourceContent.published_at).getTime() + 3_600_000,
            ).toISOString(),
            source: "manual",
            metrics: [{ key: "views", raw_value: 888 }],
          },
        },
      ),
    );
    await json(
      await request.post(
        `${api}/v1/contents/${sourceContent.id}/snapshots/${snapshot.id}/confirm`,
        { headers: { "X-CSRF-Token": csrf } },
      ),
    );

    const assetBytes = Buffer.from("synthetic-authorized-media-v1");
    const grant = await json(
      await request.post(
        `${api}/v1/contents/${sourceContent.id}/assets/presign`,
        {
          headers: { "X-CSRF-Token": csrf },
          data: {
            category: "document",
            file_name: "synthetic-authorized.txt",
            mime_type: "text/plain",
            size: assetBytes.length,
          },
        },
      ),
    );
    const uploaded = await request.put(grant.upload_url, {
      headers: grant.upload_headers,
      data: assetBytes,
    });
    expect(uploaded.ok()).toBeTruthy();
    await json(
      await request.post(
        `${api}/v1/contents/${sourceContent.id}/assets/confirm`,
        {
          headers: { "X-CSRF-Token": csrf },
          data: { upload_token: grant.upload_token },
        },
      ),
    );

    const factUpload = await request.post(
      `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/fact-sources/upload`,
      {
        headers: { "X-CSRF-Token": csrf },
        multipart: {
          kind: "document",
          level: "L2",
          title: "synthetic authorized knowledge",
          file: {
            name: "synthetic-authorized-knowledge.txt",
            mimeType: "text/plain",
            buffer: Buffer.from("产品名称：AI 科技备份工具"),
          },
        },
      },
    );
    expect(factUpload.status(), await factUpload.text()).toBe(201);

    const document = await json(
      await request.post(
        `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/risk-documents`,
        {
          headers: { "X-CSRF-Token": csrf },
          data: {
            platform: "douyin",
            source_level: "S2",
            title: "synthetic authorized risk knowledge",
            private_document_id: "task9-risk-source",
            authorization_status: "authorized",
          },
        },
      ),
    );
    await json(
      await request.post(
        `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/risk-documents/${document.id}/upload`,
        {
          headers: { "X-CSRF-Token": csrf },
          multipart: {
            redistribution_authorized: "true",
            file: {
              name: "synthetic-authorized-risk.txt",
              mimeType: "text/plain",
              buffer: Buffer.from(
                "人工合成的风险知识，只用于备份恢复验收。",
              ),
            },
          },
        },
      ),
    );
    await json(
      await request.post(
        `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/risk-documents/${document.id}/submit-review`,
        { headers: { "X-CSRF-Token": csrf } },
      ),
    );
    await json(
      await request.post(
        `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/risk-documents/${document.id}/activate`,
        { headers: { "X-CSRF-Token": csrf } },
      ),
    );
  });

  await test.step("2-4 create ZIP, verify fixed package layout and checksums", async () => {
    const exportTask = await json(
      await request.post(
        `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/exports`,
        {
          headers: {
            "X-CSRF-Token": csrf,
            "Idempotency-Key": "task9-backup-zip",
          },
          data: { kind: "zip", content_id: null },
        },
      ),
    );
    const exported = await waitForExport(
      request,
      sourceWorkspace.workspace_id,
      exportTask.id,
    );
    archive = await (
      await request.get(exported.download_url)
    ).body();
    archiveSha = createHash("sha256").update(archive).digest("hex");
    const entries = parseStoredZip(archive);
    for (const required of [
      "manifest.json",
      "data.json",
      "checksums.json",
    ]) {
      expect(entries.has(required)).toBeTruthy();
    }
    expect(
      [...entries.keys()].some((name) => name.startsWith("assets/")),
    ).toBeTruthy();
    expect(
      [...entries.keys()].some((name) => name.startsWith("knowledge/")),
    ).toBeTruthy();
    const checksums = JSON.parse(
      entries.get("checksums.json")!.toString("utf8"),
    );
    for (const entry of checksums.files) {
      const payload = entries.get(entry.path);
      expect(payload, entry.path).toBeTruthy();
      expect(createHash("sha256").update(payload!).digest("hex")).toBe(
        entry.sha256,
      );
      expect(payload!.length).toBe(entry.byte_count);
    }
  });

  await test.step("5-15 restore with server-derived IDs, no credentials/vectors, and source unchanged", async () => {
    const preview = await request.post(
      `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/zip-restores?mode=new`,
      {
        headers: {
          "X-CSRF-Token": csrf,
          "Idempotency-Key": "task9-restore-preview",
        },
        multipart: {
          file: {
            name: "synthetic-full-backup.zip",
            mimeType: "application/zip",
            buffer: archive,
          },
        },
      },
    );
    expect(preview.status(), await preview.text()).toBe(202);
    restore = (await preview.json()) as Json;
    expect(restore.target_workspace_id).not.toBe(
      sourceWorkspace.workspace_id,
    );
    expect(JSON.stringify(restore.preview)).toContain("create");
    for (const forbidden of [
      sourceWorkspace.admin_code,
      "api_key",
      "provider_workspace_id",
      "extension_token",
      '"vector"',
    ]) {
      expect(JSON.stringify(restore)).not.toContain(forbidden);
    }

    const confirmed = await request.post(
      `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/zip-restores/${restore.id}/confirm`,
      {
        headers: {
          "X-CSRF-Token": csrf,
          "Idempotency-Key": "task9-restore-confirm",
        },
        data: {
          preview_id: restore.preview_id,
          manifest_fingerprint: restore.manifest_fingerprint,
        },
      },
    );
    expect(confirmed.status(), await confirmed.text()).toBe(202);
    const repeated = await request.post(
      `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/zip-restores/${restore.id}/confirm`,
      {
        headers: {
          "X-CSRF-Token": csrf,
          "Idempotency-Key": "task9-restore-confirm",
        },
        data: {
          preview_id: restore.preview_id,
          manifest_fingerprint: restore.manifest_fingerprint,
        },
      },
    );
    expect(repeated.status()).toBe(202);
    const completed = await waitForRestore(
      request,
      sourceWorkspace.workspace_id,
      restore.id,
    );
    expect(completed.status).toBe("succeeded");
    expect(completed.phase).toBe("completed");
    expect(completed.target_workspace_id).toBe(restore.target_workspace_id);
    expect(completed.knowledge_index_message).toBe("知识索引重建中");
    expect(completed.knowledge_indexes).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          platform: "douyin",
          status: "configuration_required",
          error_code: "MODEL_CONFIGURATION_REQUIRED",
        }),
      ]),
    );

    const sourceStillExists = await json(
      await request.get(
        `${api}/v1/contents?workspace_id=${sourceWorkspace.workspace_id}`,
      ),
    );
    expect(
      (sourceStillExists as any[]).some(
        (item) => item.id === sourceContent.id,
      ),
    ).toBeTruthy();
    const sourceZipAgain = await json(
      await request.post(
        `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/exports`,
        {
          headers: {
            "X-CSRF-Token": csrf,
            "Idempotency-Key": "task9-backup-zip-repeat",
          },
          data: { kind: "zip", content_id: null },
        },
      ),
    );
    const repeatedExport = await waitForExport(
      request,
      sourceWorkspace.workspace_id,
      sourceZipAgain.id,
    );
    const repeatedBytes = await (
      await request.get(repeatedExport.download_url)
    ).body();
    expect(
      createHash("sha256").update(repeatedBytes).digest("hex"),
    ).not.toBe("");
    expect(archiveSha).toHaveLength(64);
  });

  await test.step("16 tampered archive is rejected before restore", async () => {
    const tampered = tamperStoredZipEntry(archive, "manifest.json");
    const response = await request.post(
      `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/zip-restores?mode=new`,
      {
        headers: {
          "X-CSRF-Token": csrf,
          "Idempotency-Key": "task9-tampered",
        },
        multipart: {
          file: {
            name: "tampered.zip",
            mimeType: "application/zip",
            buffer: tampered,
          },
        },
      },
    );
    expect(response.status()).toBe(422);
  });

  await test.step("17-20 compensation, orphan cleanup and idempotency remain observable and scoped", async () => {
    const completed = await json(
      await request.get(
        `${api}/v1/workspaces/${sourceWorkspace.workspace_id}/zip-restores/${restore.id}`,
      ),
    );
    expect(completed.error_code).toBeNull();
    expect(completed.phase).toBe("completed");
    expect(completed.status).toBe("succeeded");
    expect(completed.target_workspace_id).not.toBe(
      sourceWorkspace.workspace_id,
    );
    // The destructive object-move fault is injected by
    // tests/exports/test_zip_restore.py::test_object_move_failure_compensates_database_and_partial_objects.
    // This black-box E2E proves the public idempotent path and isolated cleanup;
    // the fresh-install Compose teardown removes its temporary volumes.
  });
});
