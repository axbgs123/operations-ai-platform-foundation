#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
root_dir="$(cd -- "$script_dir/.." && pwd)"
project_name="${PORTABLE_COMPOSE_PROJECT:-operations-ai-local}"
api_port="${API_PORT:-8000}"
web_port="${WEB_PORT:-3000}"
state_dir="$root_dir/.local-state"
bootstrap_file="$state_dir/bootstrap.json"
bootstrap_tmp="$state_dir/bootstrap.json.tmp"
login_file="$state_dir/首次登录信息.txt"
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

validate_bootstrap() {
  local source_file="$1"
  workspace_id="$(/usr/bin/plutil -extract workspace_id raw -o - "$source_file" 2>/dev/null || true)"
  admin_code="$(/usr/bin/plutil -extract admin_code raw -o - "$source_file" 2>/dev/null || true)"
  [[ -n "$workspace_id" && -n "$admin_code" ]]
}

write_login_file() {
  local login_tmp="$state_dir/首次登录信息.txt.tmp"
  (
    umask 077
    {
      printf '运营内容智能分析与生成平台\n'
      printf '私有入口：%s\n' "$entry_url"
      printf '工作区 ID：%s\n' "$workspace_id"
      printf '管理员邀请码：%s\n' "$admin_code"
      printf '\n此文件包含一次性敏感信息。首次登录后请妥善保管。\n'
    } >"$login_tmp"
  )
  mv "$login_tmp" "$login_file"
  chmod 600 "$login_file" 2>/dev/null || true
}

command -v docker >/dev/null 2>&1 || fail "未找到 Docker。请先安装并启动 Docker Desktop。"
docker info >/dev/null 2>&1 || fail "Docker Desktop 未运行，请启动后重试。"
docker compose version >/dev/null 2>&1 || fail "需要 Docker Compose v2。"
command -v curl >/dev/null 2>&1 || fail "系统缺少 curl，无法执行健康检查。"
[[ -x /usr/bin/plutil ]] || fail "系统缺少 /usr/bin/plutil，无法安全读取初始化响应。"

cd "$root_dir"
cp -n .env.example .env
mkdir -p "$state_dir"
chmod 700 "$state_dir" 2>/dev/null || true
export API_PORT="$api_port"
export WEB_PORT="$web_port"

printf '正在启动服务，首次构建可能需要 5–15 分钟……\n'
if ! compose --profile demo up -d --build; then
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

workspace_id=""
admin_code=""
if [[ ! -f "$bootstrap_file" ]]; then
  rm -f "$bootstrap_tmp"
  if ! curl \
    --fail \
    --silent \
    --show-error \
    --request POST \
    --header "Content-Type: application/json" \
    --data '{"name":"本地运营工作区"}' \
    --output "$bootstrap_tmp" \
    "http://127.0.0.1:${api_port}/v1/workspaces"; then
    rm -f "$bootstrap_tmp"
    printf '工作区初始化失败，服务仍在运行。重试命令：PORTABLE_NO_OPEN=1 %q\n' \
      "$root_dir/portable/启动运营工具-macOS.command" >&2
    exit 1
  fi
  if ! validate_bootstrap "$bootstrap_tmp"; then
    rm -f "$bootstrap_tmp"
    printf '工作区响应无效，未写入初始化标记。重试命令：PORTABLE_NO_OPEN=1 %q\n' \
      "$root_dir/portable/启动运营工具-macOS.command" >&2
    exit 1
  fi
  mv "$bootstrap_tmp" "$bootstrap_file"
else
  validate_bootstrap "$bootstrap_file" || fail "本机初始化状态无效；未创建新工作区，请检查 .local-state/bootstrap.json。"
fi

write_login_file
if command -v pbcopy >/dev/null 2>&1; then
  printf '%s' "$admin_code" | pbcopy || true
  printf '管理员邀请码已复制到剪贴板。\n'
fi

printf '运营工具已就绪：%s\n' "$entry_url"
printf '首次登录信息保存在：%s\n' "$login_file"
if [[ "${PORTABLE_NO_OPEN:-0}" != "1" ]]; then
  if ! open "http://127.0.0.1:${web_port}/enter"; then
    printf '未能自动打开浏览器，请手动访问：%s\n' "$entry_url" >&2
  fi
fi
