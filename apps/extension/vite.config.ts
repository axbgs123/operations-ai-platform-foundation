import { copyFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";

import { defineConfig, type Plugin } from "vite";

const root = resolve(import.meta.dirname);
const manifestPath = resolve(root, "manifest.json");

function extensionManifest(): Plugin {
  return {
    name: "extension-manifest",
    async closeBundle() {
      const dist = resolve(root, "dist");
      const contentBuild = spawnSync(
        process.execPath,
        [process.argv[1]!, "build", "--config", resolve(root, "vite.content.config.ts")],
        { cwd: root, encoding: "utf8" },
      );
      if (contentBuild.status !== 0) {
        throw new Error(contentBuild.stderr || contentBuild.stdout || "content build failed");
      }
      await mkdir(resolve(dist, "popup"), { recursive: true });
      const manifest = JSON.parse(await readFile(manifestPath, "utf8")) as {
        version: string;
      };
      const metadata = [
        `export const extensionVersion = "${manifest.version}";`,
        'export const browsers = ["chrome", "edge"];',
        'export const supportedPages = ["https://creator.douyin.com/creator-micro/content/manage*", "https://creator.xiaohongshu.com/publish/publish-manage*"];',
      ].join("\n");
      await writeFile(resolve(dist, "build-metadata.js"), metadata);
      await copyFile(manifestPath, resolve(dist, "manifest.json"));
      const popupHtml = await readFile(
        resolve(root, "src/popup/index.html"),
        "utf8",
      );
      await writeFile(
        resolve(dist, "popup.html"),
        popupHtml.replace("./main.ts", "./popup.js"),
      );
    },
  };
}

export default defineConfig({
  root,
  plugins: [extensionManifest()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      input: {
        background: resolve(root, "src/background.ts"),
        popup: resolve(root, "src/popup/main.ts"),
      },
      output: {
        entryFileNames: "[name].js",
      },
    },
  },
});
