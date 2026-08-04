#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
root_dir="$script_dir"
if [[ ! -f "$root_dir/infra/docker/compose.yml" ]]; then
  root_dir="$(cd -- "$script_dir/.." && pwd)"
fi
project_name="${PORTABLE_COMPOSE_PROJECT:-operations-ai-local}"
api_port="${API_PORT:-8000}"
web_port="${WEB_PORT:-3000}"
postgres_port="${POSTGRES_PORT:-55432}"
s3_port="${S3_PORT:-9000}"
s3_console_port="${S3_CONSOLE_PORT:-9001}"
next_public_api_url="${NEXT_PUBLIC_API_URL:-http://127.0.0.1:${api_port}}"
web_origin="${WEB_ORIGIN:-http://127.0.0.1:${web_port}}"
entry_url="http://127.0.0.1:${web_port}/enter"

compose() {
  docker compose \
    --project-name "$project_name" \
    --env-file "$root_dir/.env" \
    -f "$root_dir/infra/docker/compose.yml" \
    "$@"
}

fail() {
  printf '启动失败：%s\n' "$1" >&2
  exit 1
}

wait_for_url() {
  local url="$1"
  local timeout_seconds="$2"
  local label="$3"
  local attempt
  for ((attempt = 1; attempt <= timeout_seconds; attempt++)); do
    if curl --fail --silent --output /dev/null "$url"; then
      return 0
    fi
    sleep 1
  done
  printf '%s 在 %s 秒内未就绪。\n' "$label" "$timeout_seconds" >&2
  return 1
}

command -v docker >/dev/null 2>&1 || fail "未找到 Docker。请先安装并启动 Docker Desktop。"
docker info >/dev/null 2>&1 || fail "Docker Desktop 未运行，请启动后重试。"
docker compose version >/dev/null 2>&1 || fail "需要 Docker Compose v2。"
command -v curl >/dev/null 2>&1 || fail "系统缺少 curl，无法执行健康检查。"

cd "$root_dir"
if [[ ! -f .env ]]; then
  cp -n .env.example .env
fi
export API_PORT="$api_port"
export WEB_PORT="$web_port"
export POSTGRES_PORT="$postgres_port"
export S3_PORT="$s3_port"
export S3_CONSOLE_PORT="$s3_console_port"
export NEXT_PUBLIC_API_URL="$next_public_api_url"
export WEB_ORIGIN="$web_origin"

printf '正在构建 API 镜像，首次构建可能需要几分钟……\n'
if ! compose build api; then
  fail "API 镜像构建失败。未启动任何服务，请检查 Docker 输出后重试。"
fi
printf '正在构建 Web 镜像，首次构建可能需要几分钟……\n'
if ! compose build web; then
  fail "Web 镜像构建失败。未启动任何服务，请检查 Docker 输出后重试。"
fi
printf '正在启动服务……\n'
if ! compose --profile demo up -d --no-build; then
  fail "Docker Compose 启动失败。已有数据卷已保留，可重试本启动脚本。"
fi

if ! wait_for_url "http://127.0.0.1:${api_port}/health/ready" 120 "API"; then
  printf '诊断命令：docker compose --project-name %q --env-file %q -f %q ps\n' \
    "$project_name" "$root_dir/.env" "$root_dir/infra/docker/compose.yml" >&2
  exit 1
fi
if ! wait_for_url "$entry_url" 60 "Web 私有入口"; then
  printf '诊断命令：docker compose --project-name %q --env-file %q -f %q logs --tail=100 api web\n' \
    "$project_name" "$root_dir/.env" "$root_dir/infra/docker/compose.yml" >&2
  exit 1
fi

printf '运营工具已就绪：%s\n' "$entry_url"
if [[ "${PORTABLE_NO_OPEN:-0}" != "1" ]]; then
  if ! open "http://127.0.0.1:${web_port}/enter"; then
    printf '未能自动打开浏览器，请手动访问：%s\n' "$entry_url" >&2
  fi
fi
