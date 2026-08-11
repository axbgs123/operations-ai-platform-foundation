import { defineConfig } from "@playwright/test";

const databaseUrl = process.env.E2E_DATABASE_URL ??
  "postgresql+psycopg://operations_ai:local-development-only@localhost:55432/operations_ai";
const redisUrl = process.env.E2E_REDIS_URL ?? "redis://localhost:6379/0";
const s3Endpoint = process.env.E2E_S3_ENDPOINT ?? "http://localhost:9000";

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
        `DATABASE_URL=${JSON.stringify(databaseUrl)} REDIS_URL=${JSON.stringify(redisUrl)} S3_ENDPOINT=${JSON.stringify(s3Endpoint)} S3_PUBLIC_ENDPOINT=${JSON.stringify(s3Endpoint)} WEB_ORIGIN=http://127.0.0.1:3100 sh -c "apps/api/.venv/bin/alembic -c apps/api/alembic.ini upgrade head && PYTHONPATH=apps/api apps/api/.venv/bin/python -c 'from app.core.database import create_session_factory; from app.demo_seed import seed_demo; session = create_session_factory()(); seed_demo(session, None); session.commit(); session.close()' && apps/api/.venv/bin/fastapi dev apps/api/app/main.py --host 127.0.0.1 --port 8100"`,
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
