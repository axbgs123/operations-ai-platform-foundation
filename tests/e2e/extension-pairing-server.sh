#!/usr/bin/env bash
set -Eeuo pipefail

run_id="${EXTENSION_E2E_RUN_ID:?missing EXTENSION_E2E_RUN_ID}"
[[ "$run_id" =~ ^[a-f0-9]{12}$ ]] || { printf 'invalid extension E2E run id\n' >&2; exit 2; }
schema="extension_pairing_e2e_${run_id}"
schema_marker="${TMPDIR:-/tmp}/operations_ai_extension_pairing_e2e_schema_${run_id}"
postgres_name="${EXTENSION_E2E_POSTGRES_NAME:?missing EXTENSION_E2E_POSTGRES_NAME}"
redis_name="${EXTENSION_E2E_REDIS_NAME:?missing EXTENSION_E2E_REDIS_NAME}"
[[ "$postgres_name" == "operations_ai_extension_e2e_postgres_${run_id}" ]] || { printf 'invalid Postgres name\n' >&2; exit 2; }
[[ "$redis_name" == "operations_ai_extension_e2e_${run_id}" ]] || { printf 'invalid Redis name\n' >&2; exit 2; }
postgres_port="${EXTENSION_E2E_POSTGRES_PORT:?missing Postgres port}"
base_url="postgresql+psycopg://operations_ai:local-development-only@localhost:${postgres_port}/operations_ai"
printf '%s\n' "$schema" > "$schema_marker"
chmod 600 "$schema_marker"

cleanup() {
  apps/api/.venv/bin/python - "$schema" "$postgres_port" <<'PY' || true
import sys
import psycopg

schema = sys.argv[1]
with psycopg.connect(
    f"postgresql://operations_ai:local-development-only@localhost:{sys.argv[2]}/operations_ai"
) as connection:
    connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
PY
  docker rm -f "$redis_name" "$postgres_name" >/dev/null 2>&1 || true
  rm -f "$schema_marker"
}
trap cleanup EXIT INT TERM

apps/api/.venv/bin/python - "$postgres_port" <<'PY'
import sys
import time
import psycopg

deadline = time.monotonic() + 20
last_error = None
while time.monotonic() < deadline:
    try:
        with psycopg.connect(
            f"postgresql://operations_ai:local-development-only@localhost:{sys.argv[1]}/operations_ai"
        ):
            break
    except psycopg.OperationalError as error:
        last_error = error
        time.sleep(0.1)
else:
    raise SystemExit(f"isolated Postgres did not become ready: {last_error}")
PY

apps/api/.venv/bin/python - "$schema" "$postgres_port" <<'PY'
import sys
import psycopg

schema = sys.argv[1]
with psycopg.connect(
    f"postgresql://operations_ai:local-development-only@localhost:{sys.argv[2]}/operations_ai"
) as connection:
    connection.execute(f'CREATE SCHEMA "{schema}"')
PY

export APP_MOCK_MODE=true
export EXTENSION_E2E_SECRET="${EXTENSION_E2E_SECRET:?missing E2E secret}"
export DATABASE_URL="${base_url}?options=-csearch_path%3D${schema}"
export REDIS_URL="redis://127.0.0.1:${EXTENSION_E2E_REDIS_PORT:?missing redis port}/15"
export S3_BUCKET="operations-ai-extension-e2e-${schema}"
export WEB_ORIGIN="http://127.0.0.1:${EXTENSION_E2E_WEB_PORT:?missing web port}"
apps/api/.venv/bin/alembic -c apps/api/alembic.ini upgrade head
PYTHONPATH=apps/api:tests/e2e apps/api/.venv/bin/python -m uvicorn extension_pairing_test_app:app --host 127.0.0.1 --port "${EXTENSION_E2E_API_PORT:?missing api port}" &
server_pid=$!
wait "$server_pid"
