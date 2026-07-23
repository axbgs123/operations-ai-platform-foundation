import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  testMatch: "risk-rag.spec.ts",
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:3100",
    channel: "chrome",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: "bash tests/e2e/risk-rag-server.sh",
      cwd: "../..",
      url: "http://127.0.0.1:8100/healthz",
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command:
        "NEXT_PUBLIC_API_URL=http://127.0.0.1:8100 pnpm --filter web dev --hostname 127.0.0.1 --port 3100",
      cwd: "../..",
      url: "http://127.0.0.1:3100/enter",
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
