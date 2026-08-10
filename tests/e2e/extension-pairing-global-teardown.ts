import { spawnSync } from "node:child_process";
import { readFileSync, rmSync } from "node:fs";
import { resolve } from "node:path";

export default async function globalTeardown() {
  spawnSync("docker", ["rm", "-f", "operations_ai_extension_e2e_redis"], {
    stdio: "ignore",
  });
  const repository = resolve(process.cwd(), "../..");
  const python = resolve(repository, "apps/api/.venv/bin/python");
  const marker = resolve(process.env.TMPDIR ?? "/tmp", "operations_ai_extension_pairing_e2e_schema");
  let schema = "";
  try {
    schema = readFileSync(marker, "utf8").trim();
  } catch {
    return;
  }
  if (!/^extension_pairing_e2e_[0-9]+_[0-9]+$/.test(schema)) {
    throw new Error("refusing to clean an invalid extension E2E schema");
  }
  const cleanup = spawnSync(
    python,
    [
      "-c",
      [
        "import psycopg, sys",
        "schema = sys.argv[1]",
        "with psycopg.connect('postgresql://operations_ai:local-development-only@localhost:55432/operations_ai') as connection:",
        "    connection.execute(psycopg.sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(psycopg.sql.Identifier(schema)))",
      ].join("\n"),
      schema,
    ],
    { cwd: repository, encoding: "utf8" },
  );
  if (cleanup.status !== 0) {
    throw new Error(cleanup.stderr || cleanup.stdout || "extension E2E cleanup failed");
  }
  rmSync(marker, { force: true });
}
