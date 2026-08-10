import { spawnSync } from "node:child_process";
import { readFileSync, rmSync } from "node:fs";
import { resolve } from "node:path";

export default async function globalTeardown() {
  const runId = process.env.EXTENSION_E2E_RUN_ID ?? "";
  const postgresName = process.env.EXTENSION_E2E_POSTGRES_NAME ?? "";
  const redisName = process.env.EXTENSION_E2E_REDIS_NAME ?? "";
  if (!/^[a-f0-9]{12}$/.test(runId)) throw new Error("invalid extension E2E run id");
  if (redisName !== `operations_ai_extension_e2e_${runId}`) {
    throw new Error("refusing to clean an invalid extension E2E Redis container");
  }
  if (postgresName !== `operations_ai_extension_e2e_postgres_${runId}`) {
    throw new Error("refusing to clean an invalid extension E2E Postgres container");
  }
  const repository = resolve(import.meta.dirname, "../..");
  const python = resolve(repository, "apps/api/.venv/bin/python");
  const marker = resolve(process.env.TMPDIR ?? "/tmp", `operations_ai_extension_pairing_e2e_schema_${runId}`);
  let schema = "";
  const cleanupErrors: string[] = [];
  try {
    schema = readFileSync(marker, "utf8").trim();
  } catch {
    schema = "";
  }
  if (schema && schema !== `extension_pairing_e2e_${runId}`) {
    cleanupErrors.push("refusing to clean an invalid extension E2E schema");
    schema = "";
  }
  const postgresRunning = spawnSync(
    "docker",
    ["inspect", "--format", "{{.State.Running}}", postgresName],
    { encoding: "utf8" },
  ).stdout.trim() === "true";
  if (schema && postgresRunning) {
    const cleanup = spawnSync(
      python,
      [
        "-c",
        [
          "import psycopg, sys",
          "schema = sys.argv[1]",
          "with psycopg.connect(f'postgresql://operations_ai:local-development-only@localhost:{sys.argv[2]}/operations_ai') as connection:",
          "    connection.execute(psycopg.sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(psycopg.sql.Identifier(schema)))",
        ].join("\n"),
        schema,
        process.env.EXTENSION_E2E_POSTGRES_PORT ?? "",
      ],
      { cwd: repository, encoding: "utf8" },
    );
    if (cleanup.status !== 0) {
      cleanupErrors.push(
        cleanup.stderr.trim() || cleanup.stdout.trim() || "extension E2E schema cleanup failed",
      );
    }
  }
  try {
    spawnSync("docker", ["rm", "-f", redisName, postgresName], { encoding: "utf8" });
  } finally {
    rmSync(marker, { force: true });
  }
  for (const containerName of [redisName, postgresName]) {
    const inspection = spawnSync("docker", ["inspect", containerName], { encoding: "utf8" });
    if (inspection.error) {
      cleanupErrors.push(`could not verify removal of ${containerName}: ${inspection.error.message}`);
    } else if (inspection.status === 0) {
      cleanupErrors.push(`extension E2E container still exists after cleanup: ${containerName}`);
    } else {
      const diagnostic = `${inspection.stderr}\n${inspection.stdout}`.toLowerCase();
      if (!diagnostic.includes("no such object") && !diagnostic.includes("no such container")) {
        cleanupErrors.push(`could not verify removal of ${containerName}: ${diagnostic.trim()}`);
      }
    }
  }
  if (cleanupErrors.length > 0) {
    throw new Error(`extension E2E cleanup failed:\n${cleanupErrors.join("\n")}`);
  }
}
