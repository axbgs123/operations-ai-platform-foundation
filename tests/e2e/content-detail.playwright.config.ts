import { defineConfig } from "@playwright/test";


const databaseUrl = process.env.CONTENT_DETAIL_E2E_DATABASE_URL;
if (!databaseUrl) {
  throw new Error(
    "CONTENT_DETAIL_E2E_DATABASE_URL must point to an isolated disposable database",
  );
}
const apiPort = process.env.CONTENT_DETAIL_E2E_API_PORT ?? "18100";
const webPort = process.env.CONTENT_DETAIL_E2E_WEB_PORT ?? "13100";
const apiUrl = `http://127.0.0.1:${apiPort}`;
const webUrl = `http://127.0.0.1:${webPort}`;

export default defineConfig({
  testDir: ".",
  testMatch: "content-detail.spec.ts",
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: webUrl,
    channel: "chrome",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command:
        "apps/api/.venv/bin/alembic -c apps/api/alembic.ini upgrade head "
        + "&& apps/api/.venv/bin/fastapi dev apps/api/app/main.py "
        + `--host 127.0.0.1 --port ${apiPort}`,
      cwd: "../..",
      env: {
        APP_MOCK_MODE: "true",
        DATABASE_URL: databaseUrl,
        WEB_ORIGIN: webUrl,
      },
      url: `${apiUrl}/healthz`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command:
        `NEXT_PUBLIC_API_URL=${apiUrl} pnpm --filter web dev `
        + `--hostname 127.0.0.1 --port ${webPort}`,
      cwd: "../..",
      url: `${webUrl}/enter`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
