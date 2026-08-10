#!/usr/bin/env bash
set -Eeuo pipefail

run_id="${EXTENSION_E2E_RUN_ID:?missing EXTENSION_E2E_RUN_ID}"
[[ "$run_id" =~ ^[a-f0-9]{12}$ ]] || { printf 'invalid extension E2E run id\n' >&2; exit 2; }
schema="extension_pairing_e2e_${run_id}"
schema_marker="${TMPDIR:-/tmp}/operations_ai_extension_pairing_e2e_schema_${run_id}"
base_url="postgresql+psycopg://operations_ai:local-development-only@localhost:55432/operations_ai"
printf '%s\n' "$schema" > "$schema_marker"
chmod 600 "$schema_marker"

cleanup() {
  apps/api/.venv/bin/python - "$schema" <<'PY'
import sys
import psycopg

schema = sys.argv[1]
with psycopg.connect(
    "postgresql://operations_ai:local-development-only@localhost:55432/operations_ai"
) as connection:
    connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
PY
}
trap cleanup EXIT INT TERM

apps/api/.venv/bin/python - "$schema" <<'PY'
import sys
import psycopg

schema = sys.argv[1]
with psycopg.connect(
    "postgresql://operations_ai:local-development-only@localhost:55432/operations_ai"
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
