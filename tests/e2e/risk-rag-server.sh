#!/usr/bin/env bash
set -euo pipefail

schema="risk_rag_e2e_${RANDOM}_$(date +%s)"
base_url="postgresql+psycopg://operations_ai:local-development-only@localhost:55432/operations_ai"

apps/api/.venv/bin/python - "$schema" <<'PY'
import sys
import psycopg

schema = sys.argv[1]
with psycopg.connect(
    "postgresql://operations_ai:local-development-only@localhost:55432/operations_ai"
) as connection:
    connection.execute(f'CREATE SCHEMA "{schema}"')
PY

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

export DATABASE_URL="${base_url}?options=-csearch_path%3D${schema}"
export WEB_ORIGIN="http://127.0.0.1:3100"
apps/api/.venv/bin/alembic -c apps/api/alembic.ini upgrade head
apps/api/.venv/bin/fastapi dev apps/api/app/main.py --host 127.0.0.1 --port 8100 &
server_pid=$!
wait "$server_pid"
