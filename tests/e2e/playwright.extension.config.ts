import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  testMatch: "extension-pairing-safe-capture.spec.ts",
  globalTeardown: "./extension-pairing-global-teardown.ts",
  fullyParallel: false,
  workers: 1,
  timeout: 120_000,
  use: {
    baseURL: "http://127.0.0.1:3120",
    channel: "chrome",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command:
        "docker run --rm --name operations_ai_extension_e2e_redis --tmpfs /data --publish 127.0.0.1:56379:6379 redis:8.2.1-alpine",
      port: 56379,
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: "bash tests/e2e/extension-pairing-server.sh",
      cwd: "../..",
      url: "http://127.0.0.1:8120/healthz",
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command:
        "NEXT_PUBLIC_API_URL=http://127.0.0.1:8120 pnpm --filter web dev --hostname 127.0.0.1 --port 3120",
      cwd: "../..",
      url: "http://127.0.0.1:3120/enter",
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
