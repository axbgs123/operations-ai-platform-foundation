#!/usr/bin/env bash
set -Eeuo pipefail

readonly project_prefix="operations_ai_task7_"
readonly project_name="${project_prefix}${$}_${RANDOM}"
readonly root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly compose_file="$root_dir/infra/docker/compose.yml"
env_file="$(mktemp "${TMPDIR:-/tmp}/operations-ai-task7.env.XXXXXX")"
diagnostics_dir="$(mktemp -d "${TMPDIR:-/tmp}/operations-ai-task7-diagnostics.XXXXXX")"
api_port="$((38000 + RANDOM % 1000))"
web_port="$((39000 + RANDOM % 1000))"
s3_port="$((40000 + RANDOM % 1000))"
s3_console_port="$((41000 + RANDOM % 1000))"
postgres_port="$((42000 + RANDOM % 1000))"

compose() {
  docker compose --project-name "$project_name" --env-file "$env_file" -f "$compose_file" "$@"
}

wait_healthy() {
  local service="$1"
  local url="$2"
  local attempt
  for attempt in $(seq 1 60); do
    if [[ "$service" == "api" ]] && compose exec -T api /app/.venv/bin/python -c "import urllib.request; urllib.request.urlopen('$url')" >/dev/null 2>&1; then
      return 0
    fi
    if [[ "$service" == "web" ]] && compose exec -T web node -e "fetch('$url').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  printf '%s did not become healthy within 60 seconds\n' "$service" >&2
  return 1
}

wait_completed() {
  local service="$1"
  local container_id
  local exit_code

  container_id="$(compose --profile demo ps -a -q "$service")"
  if [[ -z "$container_id" ]]; then
    printf 'one-shot service %s did not create a container\n' "$service" >&2
    return 1
  fi
  exit_code="$(docker wait "$container_id")"
  if [[ "$exit_code" != "0" ]]; then
    printf 'one-shot service %s exited with code %s\n' "$service" "$exit_code" >&2
    return 1
  fi
}

wait_for_one_shots() {
  local service
  for service in migrate bucket-init demo-seed; do
    wait_completed "$service"
  done
}

cleanup() {
  status=$?
  if [[ "$project_name" != ${project_prefix}* ]]; then
    printf 'refusing to clean non-test project %s\n' "$project_name" >&2
    exit 1
  fi
  compose ps >"$diagnostics_dir/ps.txt" 2>&1 || true
  compose logs --no-color >"$diagnostics_dir/compose.log" 2>&1 || true
  compose --profile demo --profile e2e down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -f "$env_file"
  if [[ "$status" -ne 0 ]]; then
    printf 'fresh-install diagnostics retained at %s\n' "$diagnostics_dir" >&2
  else
    rm -rf "$diagnostics_dir"
  fi
  exit "$status"
}
trap cleanup EXIT

if ! docker info >/dev/null 2>&1; then
  printf 'Docker daemon is not available; start Docker Desktop and retry.\n' >&2
  exit 1
fi
if [[ ! -f "$root_dir/.env.example" ]]; then
  printf '.env.example is required for isolated verification.\n' >&2
  exit 1
fi
for port in "$api_port" "$web_port" "$s3_port" "$s3_console_port" "$postgres_port"; do
  if ! python3 - "$port" <<'PY'
import socket
import sys
s = socket.socket()
try:
    s.bind(("127.0.0.1", int(sys.argv[1])))
finally:
    s.close()
PY
  then
    printf 'test port %s is unavailable; retry the script.\n' "$port" >&2
    exit 1
  fi
done

cp "$root_dir/.env.example" "$env_file"
printf '%s\n' \
  'APP_ENV=development' \
  'APP_MOCK_MODE=true' \
  'POSTGRES_DB=operations_ai_task7' \
  'POSTGRES_USER=operations_ai_task7' \
  'POSTGRES_PASSWORD=task7-local-password-only' \
  'S3_ACCESS_KEY=task7-access' \
  'S3_SECRET_KEY=task7-local-secret-only' \
  'STORAGE_SIGNING_SECRET=task7-local-signing-secret-only-000000000000' \
  'MODEL_SECRET_ENCRYPTION_KEY=task7-local-model-secret-only-00000000000000' \
  'SESSION_SIGNING_SECRET=task7-local-session-signing-secret-only-0000000000' \
  "API_PORT=$api_port" \
  "WEB_PORT=$web_port" \
  "S3_PORT=$s3_port" \
  "S3_CONSOLE_PORT=$s3_console_port" \
  "POSTGRES_PORT=$postgres_port" \
  'NEXT_PUBLIC_API_URL=http://api:8000' \
  'WEB_ORIGIN=http://web:3000' >>"$env_file"

printf 'Building and starting isolated Compose project %s\n' "$project_name"
compose --profile demo up --build -d
wait_for_one_shots
wait_healthy api http://localhost:8000/health/ready
wait_healthy web http://localhost:3000/demo
compose exec -T postgres psql -U operations_ai_task7 -d operations_ai_task7 -Atc \
  "SELECT count(*) || '|' || (SELECT count(*) FROM contents WHERE workspace_id = (SELECT id FROM workspaces WHERE status = 'demo:synthetic-ai-tech-v1'));" | grep -qx '1|5'
compose exec -T api /app/.venv/bin/python -c \
  "from app.core.storage import get_storage; assert get_storage().inspect_object('demo/synthetic-ai-tech-v1/synthetic-cover.txt')"
compose --profile e2e build e2e
compose --profile e2e run --rm e2e
compose exec -T redis redis-cli SET task7:persistence ok >/dev/null

printf 'Stopping without deleting volumes and restarting %s\n' "$project_name"
compose --profile demo down
compose --profile demo up -d
wait_for_one_shots
wait_healthy api http://localhost:8000/health/ready
wait_healthy web http://localhost:3000/demo
compose exec -T postgres psql -U operations_ai_task7 -d operations_ai_task7 -Atc \
  "SELECT count(*) || '|' || (SELECT count(*) FROM contents WHERE workspace_id = (SELECT id FROM workspaces WHERE status = 'demo:synthetic-ai-tech-v1'));" | grep -qx '1|5'
compose exec -T api /app/.venv/bin/python -c \
  "from app.core.storage import get_storage; assert get_storage().inspect_object('demo/synthetic-ai-tech-v1/synthetic-cover.txt')"
compose exec -T redis redis-cli GET task7:persistence | grep -qx 'ok'
compose --profile e2e run --rm e2e
printf 'Fresh install verification complete; isolated project will now be removed.\n'
