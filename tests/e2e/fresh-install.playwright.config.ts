import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  testMatch: [
    "fresh-install.spec.ts",
    "full-loop.spec.ts",
    "backup-restore.spec.ts",
    "demo.spec.ts",
  ],
  workers: 1,
  use: {
    baseURL: process.env.FRESH_INSTALL_WEB_URL ?? "http://127.0.0.1:3000",
    trace: "retain-on-failure",
  },
});
