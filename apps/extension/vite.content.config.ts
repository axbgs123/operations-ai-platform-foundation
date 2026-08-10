import { resolve } from "node:path";

import { defineConfig } from "vite";

const root = resolve(import.meta.dirname);

export default defineConfig({
  root,
  build: {
    outDir: "dist",
    emptyOutDir: false,
    rollupOptions: {
      input: resolve(root, "src/content.ts"),
      output: {
        entryFileNames: "content.js",
        inlineDynamicImports: true,
      },
    },
  },
});
