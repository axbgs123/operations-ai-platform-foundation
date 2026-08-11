import { createHash } from "node:crypto";
import { readFile, readdir, stat } from "node:fs/promises";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

type Manifest = {
  manifest_version: number;
  version: string;
  key?: string;
  permissions?: string[];
  host_permissions?: string[];
  optional_host_permissions?: string[];
  background?: { service_worker?: string; type?: string };
  content_scripts?: Array<{ matches?: string[]; js?: string[] }>;
  content_security_policy?: { extension_pages?: string };
  commands?: Record<string, { suggested_key?: Record<string, string> }>;
};

const extensionRoot = resolve(import.meta.dirname, "..");
const manifestPath = resolve(extensionRoot, "manifest.json");
const metadataPath = resolve(extensionRoot, "src/build-metadata.ts");
const installationGuidePath = resolve(extensionRoot, "../../docs/open-source/extension-installation.md");
const distRoot = resolve(extensionRoot, "dist");

async function readManifest(path = manifestPath): Promise<Manifest> {
  return JSON.parse(await readFile(path, "utf8")) as Manifest;
}

describe("least-privilege Manifest V3", () => {
  it("publishes a stable public identity for exact API CORS allowlisting", async () => {
    const manifest = await readManifest();
    expect(manifest.key).toBeTruthy();
    const digest = createHash("sha256")
      .update(Buffer.from(manifest.key!, "base64"))
      .digest("hex")
      .slice(0, 32);
    const extensionId = digest.replace(/[0-9a-f]/g, (digit) =>
      String.fromCharCode("a".charCodeAt(0) + Number.parseInt(digit, 16)),
    );

    expect(extensionId).toBe("mdbmlilohlhmjmcmkpbpjhldganompcl");
  });

  it("uses Manifest V3 and only the justified extension permissions", async () => {
    const manifest = await readManifest();

    expect(manifest.manifest_version).toBe(3);
    expect(manifest.permissions?.sort()).toEqual(
      ["activeTab", "scripting", "storage"].sort(),
    );
  });

  it("registers the documented full-page shortcut without broadening permissions", async () => {
    const manifest = await readManifest();

    expect(manifest.commands?.["capture-full-page"]?.suggested_key).toEqual({
      default: "Ctrl+Shift+8",
      mac: "Command+Shift+8",
    });
  });

  it("rejects sensitive, broad, and interception permissions", async () => {
    const manifest = await readManifest();
    const declared = new Set([
      ...(manifest.permissions ?? []),
      ...(manifest.host_permissions ?? []),
    ]);

    for (const forbidden of [
      "cookies",
      "webRequest",
      "webRequestBlocking",
      "tabs",
      "history",
      "<all_urls>",
    ]) {
      expect(declared.has(forbidden)).toBe(false);
    }
  });

  it("limits host access to explicit Douyin and Xiaohongshu operations pages", async () => {
    const manifest = await readManifest();

    expect(manifest.host_permissions).toEqual([
      "https://creator.douyin.com/creator-micro/content/manage*",
      "https://creator.xiaohongshu.com/publish/publish-manage*",
    ]);
    expect(manifest.content_scripts?.flatMap((script) => script.matches ?? [])).toEqual(
      manifest.host_permissions,
    );
    expect(manifest.optional_host_permissions).toEqual([
      "https://*/*",
      "http://localhost/*",
      "http://127.0.0.1/*",
      "http://[::1]/*",
    ]);
    expect(manifest.optional_host_permissions).not.toContain("<all_urls>");
  });

  it("uses a local module service worker and a restrictive extension CSP", async () => {
    const manifest = await readManifest();

    expect(manifest.background).toEqual({
      service_worker: "background.js",
      type: "module",
    });
    expect(manifest.content_security_policy?.extension_pages).toBe(
      "script-src 'self'; object-src 'self'",
    );
  });

  it("packages the manifest content script as a classic self-contained script", async () => {
    const manifest = await readManifest();
    const contentScripts = manifest.content_scripts?.flatMap((entry) => entry.js ?? []) ?? [];

    expect(contentScripts).toEqual(["content.js"]);
    for (const script of contentScripts) {
      const source = await readFile(resolve(distRoot, script), "utf8");
      expect(source).not.toMatch(/^\s*import(?:\s|\{|\*)/m);
      expect(source).not.toMatch(/^\s*export(?:\s|\{|\*)/m);
    }
  });

  it("publishes versioned build metadata for the shared Chrome and Edge artifact", async () => {
    const manifest = await readManifest();
    const metadata = await readFile(metadataPath, "utf8");
    const packagedMetadata = await readFile(
      resolve(distRoot, "build-metadata.js"),
      "utf8",
    );

    expect(metadata).toContain(`extensionVersion = "${manifest.version}"`);
    expect(metadata).toContain('browsers = ["chrome", "edge"]');
    expect(metadata).toContain("creator.douyin.com");
    expect(metadata).toContain("creator.xiaohongshu.com");
    expect(manifest.version).toBe("0.3.0");
    expect(packagedMetadata).toContain(
      `extensionVersion = "${manifest.version}"`,
    );
    expect(packagedMetadata).toContain("creator.douyin.com");
    expect(packagedMetadata).toContain("creator.xiaohongshu.com");
  });

  it("keeps the installation handoff version and archive names aligned with the manifest", async () => {
    const manifest = await readManifest();
    const installationGuide = await readFile(installationGuidePath, "utf8");

    expect(installationGuide).toContain(`当前扩展版本为 \`${manifest.version}\``);
    expect(installationGuide).toContain(`operations-capture-extension-chrome-${manifest.version}.zip`);
    expect(installationGuide).toContain(`版本为 \`${manifest.version}\``);
  });

  it("keeps packaged files free of secrets, accounts, screenshots, and server configuration", async () => {
    const files = await readdir(distRoot, { recursive: true });
    const forbiddenName = /(screenshot|cookie|invite|token|account|private)/i;
    const forbiddenContent =
      /(sk-[a-z0-9_-]{20,}|BEGIN .* PRIVATE KEY|synthetic-invite|opaque-session-token|https:\/\/ops\.example\.com)/i;

    expect(files).not.toEqual(
      expect.arrayContaining([expect.stringMatching(forbiddenName)]),
    );
    for (const relativePath of files) {
      if (!(await stat(resolve(distRoot, relativePath))).isFile()) continue;
      const content = await readFile(resolve(distRoot, relativePath), "utf8");
      expect(content).not.toMatch(forbiddenContent);
    }
  });
});
