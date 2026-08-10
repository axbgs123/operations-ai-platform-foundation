import { defineConfig } from "@playwright/test";
import { randomBytes } from "node:crypto";

const runId = process.env.EXTENSION_E2E_RUN_ID ?? randomBytes(6).toString("hex");
if (!/^[a-f0-9]{12}$/.test(runId)) throw new Error("invalid extension E2E run id");
const portBase = 20_000 + (Number.parseInt(runId.slice(0, 6), 16) % 7_000) * 3;
const redisPort = portBase;
const apiPort = portBase + 1;
const webPort = portBase + 2;
const redisName = `operations_ai_extension_e2e_${runId}`;
const e2eSecret = process.env.EXTENSION_E2E_SECRET ?? randomBytes(24).toString("hex");
Object.assign(process.env, {
  EXTENSION_E2E_RUN_ID: runId,
  EXTENSION_E2E_REDIS_NAME: redisName,
  EXTENSION_E2E_REDIS_PORT: String(redisPort),
  EXTENSION_E2E_API_PORT: String(apiPort),
  EXTENSION_E2E_WEB_PORT: String(webPort),
  EXTENSION_E2E_SECRET: e2eSecret,
});

export default defineConfig({
  testDir: ".",
  testMatch: "extension-pairing-safe-capture.spec.ts",
  globalTeardown: "./extension-pairing-global-teardown.ts",
  globalSetup: "./extension-pairing-global-setup.ts",
  fullyParallel: false,
  workers: 1,
  timeout: 120_000,
  use: {
    baseURL: `http://127.0.0.1:${webPort}`,
    channel: "chrome",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command:
        `docker run --rm --name ${redisName} --tmpfs /data --publish 127.0.0.1:${redisPort}:6379 redis:8.2.1-alpine`,
      port: redisPort,
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: "bash tests/e2e/extension-pairing-server.sh",
      cwd: "../..",
      url: `http://127.0.0.1:${apiPort}/healthz`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command:
        `NEXT_PUBLIC_API_URL=http://127.0.0.1:${apiPort} pnpm --filter web dev --hostname 127.0.0.1 --port ${webPort}`,
      cwd: "../..",
      url: `http://127.0.0.1:${webPort}/enter`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
