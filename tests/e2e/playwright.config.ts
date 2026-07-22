import { defineConfig } from "@playwright/test";


export default defineConfig({
  testDir: ".",
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:3100",
    channel: "chrome",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command:
        "DATABASE_URL=postgresql+psycopg://operations_ai:local-development-only@localhost:55432/operations_ai WEB_ORIGIN=http://127.0.0.1:3100 sh -c 'apps/api/.venv/bin/alembic -c apps/api/alembic.ini upgrade head && apps/api/.venv/bin/fastapi dev apps/api/app/main.py --host 127.0.0.1 --port 8100'",
      cwd: "../..",
      url: "http://127.0.0.1:8100/healthz",
      reuseExistingServer: true,
      timeout: 120_000,
    },
    {
      command:
        "NEXT_PUBLIC_API_URL=http://127.0.0.1:8100 pnpm --filter web dev --hostname 127.0.0.1 --port 3100",
      cwd: "../..",
      url: "http://127.0.0.1:3100/enter",
      reuseExistingServer: true,
      timeout: 120_000,
    },
  ],
});
