import { createHash } from "node:crypto";
import {
  cp,
  mkdir,
  readFile,
  readdir,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import { basename, relative, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const root = resolve(import.meta.dirname, "..");
const dist = resolve(root, "dist");
const release = resolve(root, "release");
const unpacked = resolve(release, "unpacked");

const sha256 = (buffer) =>
  createHash("sha256").update(buffer).digest("hex");

async function filesIn(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const output = [];
  for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
    const path = resolve(directory, entry.name);
    if (entry.isDirectory()) output.push(...(await filesIn(path)));
    else output.push(path);
  }
  return output;
}

await stat(resolve(dist, "manifest.json"));
await rm(release, { recursive: true, force: true });
await mkdir(unpacked, { recursive: true });
await cp(dist, unpacked, { recursive: true });
await cp(resolve(root, "PRIVACY.md"), resolve(unpacked, "PRIVACY.md"));
await cp(
  resolve(root, "supported-pages.json"),
  resolve(unpacked, "supported-pages.json"),
);

const packageJson = JSON.parse(
  await readFile(resolve(root, "package.json"), "utf8"),
);
const sharedSchemasPackageJson = JSON.parse(
  await readFile(resolve(root, "../../packages/shared-schemas/package.json"), "utf8"),
);
const sbomPackage = (SPDXID, name, versionInfo) => ({
  SPDXID,
  name,
  versionInfo,
  downloadLocation: "NOASSERTION",
  licenseConcluded: "NOASSERTION",
  licenseDeclared: "NOASSERTION",
  filesAnalyzed: false,
});
const extensionPackage = sbomPackage(
  "SPDXRef-Package-extension",
  packageJson.name,
  packageJson.version,
);
const sharedSchemasPackage = sbomPackage(
  "SPDXRef-Package-operations-ai-shared-schemas",
  sharedSchemasPackageJson.name,
  sharedSchemasPackageJson.version,
);
const sharedRuntimePackages = Object.entries(
  sharedSchemasPackageJson.dependencies ?? {},
).map(([name, version]) =>
  sbomPackage(
    `SPDXRef-Package-${name.replace(/[^A-Za-z0-9.-]+/g, "-")}-${version}`,
    name,
    version,
  ),
);
const extensionSbomPackages = [
  extensionPackage,
  sharedSchemasPackage,
  ...sharedRuntimePackages,
];
await writeFile(
  resolve(unpacked, "sbom.spdx.json"),
  JSON.stringify(
    {
      spdxVersion: "SPDX-2.3",
      dataLicense: "CC0-1.0",
      SPDXID: "SPDXRef-DOCUMENT",
      name: packageJson.name,
      documentNamespace: `https://operations-ai.invalid/spdx/extension/${sha256(Buffer.from(JSON.stringify({ packageJson, sharedSchemasPackageJson })))}`,
      creationInfo: {
        creators: ["Tool: package-extension.mjs"],
        created: "2026-07-28T00:00:00Z",
      },
      comment: "Scope: extension production runtime dependencies from locked workspace package metadata; development-only tooling is excluded.",
      packages: extensionSbomPackages,
      relationships: [
        ...extensionSbomPackages.map(({ SPDXID }) => ({
          spdxElementId: "SPDXRef-DOCUMENT",
          relationshipType: "DESCRIBES",
          relatedSpdxElement: SPDXID,
        })),
        {
          spdxElementId: extensionPackage.SPDXID,
          relationshipType: "DEPENDS_ON",
          relatedSpdxElement: sharedSchemasPackage.SPDXID,
        },
        ...sharedRuntimePackages.map(({ SPDXID }) => ({
          spdxElementId: sharedSchemasPackage.SPDXID,
          relationshipType: "DEPENDS_ON",
          relatedSpdxElement: SPDXID,
        })),
      ],
    },
    null,
    2,
  ),
);

const forbiddenNames = [
  "node_modules",
  ".env",
  "test-results",
  "screenshots",
];
const files = await filesIn(unpacked);
for (const file of files) {
  const path = relative(unpacked, file);
  if (
    forbiddenNames.some((part) => path.split("/").includes(part)) ||
    path.endsWith(".map") ||
    path.endsWith(".log")
  ) {
    throw new Error(`forbidden release artifact: ${path}`);
  }
}

const manifest = [];
for (const file of files) {
  const buffer = await readFile(file);
  const text = buffer.toString("utf8");
  if (
    /sk-[A-Za-z0-9]{10,}|eyJ[A-Za-z0-9_-]{20,}/.test(text) ||
    /<script[^>]+src=["']https?:\/\//i.test(text) ||
    /\beval\s*\(|new Function\s*\(/.test(text)
  ) {
    throw new Error(`sensitive or remote code found in ${relative(unpacked, file)}`);
  }
  manifest.push({
    path: relative(unpacked, file),
    sha256: sha256(buffer),
    bytes: buffer.byteLength,
  });
}
manifest.push({
  path: "release-manifest.json",
  sha256: null,
  bytes: null,
});
await writeFile(
  resolve(unpacked, "release-manifest.json"),
  JSON.stringify(
    {
      extensionVersion: packageJson.version,
      browsers: ["chrome", "edge"],
      validationScope: "fixture_and_local_build_only",
      realPageValidation: "unverified",
      files: manifest,
    },
    null,
    2,
  ),
);

const canonical = resolve(release, `operations-capture-extension-${packageJson.version}.zip`);
const zipped = spawnSync("/usr/bin/zip", ["-X", "-q", "-r", canonical, "."], {
  cwd: unpacked,
  encoding: "utf8",
});
if (zipped.status !== 0) throw new Error(zipped.stderr || "zip failed");

const chromeArchive = resolve(
  release,
  `operations-capture-extension-chrome-${packageJson.version}.zip`,
);
const edgeArchive = resolve(
  release,
  `operations-capture-extension-edge-${packageJson.version}.zip`,
);
await cp(canonical, chromeArchive);
await cp(canonical, edgeArchive);
await rm(canonical);

const archives = [chromeArchive, edgeArchive];
await writeFile(
  resolve(release, "hashes.json"),
  JSON.stringify(
    Object.fromEntries(
      await Promise.all(
        archives.map(async (archive) => [
          basename(archive),
          sha256(await readFile(archive)),
        ]),
      ),
    ),
    null,
    2,
  ),
);
