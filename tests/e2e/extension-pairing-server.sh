#!/usr/bin/env bash
set -Eeuo pipefail

schema="extension_pairing_e2e_${RANDOM}_$(date +%s)"
schema_marker="${TMPDIR:-/tmp}/operations_ai_extension_pairing_e2e_schema"
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
export DATABASE_URL="${base_url}?options=-csearch_path%3D${schema}"
export REDIS_URL="redis://127.0.0.1:56379/15"
export S3_BUCKET="operations-ai-extension-e2e-${schema}"
export WEB_ORIGIN="http://127.0.0.1:3120"
apps/api/.venv/bin/alembic -c apps/api/alembic.ini upgrade head
PYTHONPATH=apps/api apps/api/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8120 &
server_pid=$!
wait "$server_pid"
