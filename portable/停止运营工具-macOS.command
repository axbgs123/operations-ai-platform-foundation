#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
root_dir="$(cd -- "$script_dir/.." && pwd)"

docker compose \
  --project-name "${PORTABLE_COMPOSE_PROJECT:-operations-ai-local}" \
  --env-file "$root_dir/.env" \
  -f "$root_dir/infra/docker/compose.yml" \
  --profile demo down

printf '运营工具已停止，本地数据卷保持不变。\n'
