#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

readonly project_prefix="operations_ai_portable_test_"
readonly root_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
readonly python_bin="$root_dir/apps/api/.venv/bin/python"
readonly expected_extension_version="0.2.0"
readonly evidence_allowed_fields="schema_version macos_runtime source_commit zip_sha256 extension_version started_at finished_at docker_version docker_compose_version workspace_id owner_member_id editor_member_id account_id content_id member_count cleanup"

mode=""
zip_argument=""
version="0.1.0"
source_date_epoch="1785744000"

usage() {
  cat <<'EOF'
用法：
  bash scripts/verify-portable-release.sh --zip <ZIP路径>
  bash scripts/verify-portable-release.sh --build [--version 0.1.0] [--source-date-epoch 1785744000]
EOF
}

fail() {
  printf '便携包验收失败：%s\n' "$1" >&2
  exit 1
}

while (($#)); do
  case "$1" in
    --build)
      [[ -z "$mode" ]] || fail "--build 与 --zip 不能同时使用"
      mode="build"
      shift
      ;;
    --zip)
      [[ -z "$mode" ]] || fail "--build 与 --zip 不能同时使用"
      (($# >= 2)) || fail "--zip 缺少路径"
      mode="zip"
      zip_argument="$2"
      shift 2
      ;;
    --version)
      (($# >= 2)) || fail "--version 缺少值"
      version="$2"
      shift 2
      ;;
    --source-date-epoch)
      (($# >= 2)) || fail "--source-date-epoch 缺少值"
      source_date_epoch="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      usage >&2
      fail "未知参数：$1"
      ;;
  esac
done

[[ -n "$mode" ]] || {
  usage >&2
  fail "必须明确指定 --zip 或 --build"
}
[[ -x "$python_bin" ]] || fail "缺少 API Python 环境：$python_bin"

if [[ "$mode" == "build" ]]; then
  "$python_bin" "$root_dir/scripts/build-portable-release.py" \
    --repository "$root_dir" \
    --output-dir "$root_dir/dist/portable" \
    --version "$version" \
    --source-date-epoch "$source_date_epoch"
  zip_argument="$root_dir/dist/portable/operations-ai-portable-${version}.zip"
fi

zip_path="$(
  "$python_bin" - "$zip_argument" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1]).expanduser().resolve(strict=True)
if not path.is_file():
    raise SystemExit("ZIP path is not a regular file")
print(path)
PY
)" || fail "无法解析 ZIP 路径"

"$python_bin" "$root_dir/scripts/release-security.py" \
  verify-portable-release \
  --path "$zip_path"

command -v docker >/dev/null 2>&1 || fail "未找到 Docker"
docker info >/dev/null 2>&1 || fail "Docker Desktop 未运行"
docker compose version >/dev/null 2>&1 || fail "需要 Docker Compose v2"
command -v curl >/dev/null 2>&1 || fail "未找到 curl"

started_at="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
zip_sha256="$(
  "$python_bin" - "$zip_path" <<'PY'
from hashlib import sha256
from pathlib import Path
import sys

print(sha256(Path(sys.argv[1]).read_bytes()).hexdigest())
PY
)"
source_commit="$(
  "$python_bin" - "$zip_path" <<'PY'
import json
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1]) as archive:
    manifest = json.loads(archive.read("release-manifest.json"))
commit = manifest.get("source_commit")
if not isinstance(commit, str) or len(commit) != 40:
    raise SystemExit("release manifest has no exact source commit")
print(commit)
PY
)"
docker_version="$(docker version --format '{{.Server.Version}}')"
docker_compose_version="$(docker compose version --short)"

temporary_root="$(mktemp -d "${TMPDIR:-/tmp}/operations-ai-portable-acceptance.XXXXXX")"
unpacked_root="$temporary_root/unpacked"
mkdir -p "$unpacked_root"
project_name="${project_prefix}$(date +%s)_$$_${RANDOM}"
cleanup_done=0

compose() {
  docker compose \
    --project-name "$project_name" \
    --env-file "$unpacked_root/.env" \
    -f "$unpacked_root/infra/docker/compose.yml" \
    "$@"
}

verify_project_absent() {
  local containers networks volumes
  containers="$(docker ps -aq --filter "label=com.docker.compose.project=$project_name")"
  networks="$(docker network ls -q --filter "label=com.docker.compose.project=$project_name")"
  volumes="$(docker volume ls -q --filter "label=com.docker.compose.project=$project_name")"
  [[ -z "$containers" && -z "$networks" && -z "$volumes" ]]
}

cleanup_resources() {
  [[ "$project_name" == "$project_prefix"* ]] || {
    printf 'refusing to clean non-test project %s\n' "$project_name" >&2
    return 1
  }
  if [[ -f "$unpacked_root/infra/docker/compose.yml" && -f "$unpacked_root/.env" ]]; then
    compose --profile demo down --volumes --remove-orphans >/dev/null 2>&1 || true
  fi
  rm -rf "$temporary_root"
  verify_project_absent
}

cleanup() {
  local status=$?
  trap - EXIT
  if [[ "$cleanup_done" -eq 0 ]]; then
    cleanup_resources || {
      printf '便携包验收清理失败，仅检查项目：%s\n' "$project_name" >&2
      exit 1
    }
  fi
  exit "$status"
}
trap cleanup EXIT

select_loopback_port() {
  "$python_bin" <<'PY'
import socket

with socket.socket() as listener:
    listener.bind(("127.0.0.1", 0))
    print(listener.getsockname()[1])
PY
}

api_port="$(select_loopback_port)"
web_port="$(select_loopback_port)"
postgres_port="$(select_loopback_port)"
s3_port="$(select_loopback_port)"
s3_console_port="$(select_loopback_port)"

"$python_bin" - "$zip_path" "$unpacked_root" <<'PY'
from pathlib import Path
import stat
import sys
import zipfile

zip_path = Path(sys.argv[1])
destination = Path(sys.argv[2])
with zipfile.ZipFile(zip_path) as archive:
    archive.extractall(destination)
    for entry in archive.infolist():
        mode = (entry.external_attr >> 16) & 0xFFFF
        if mode:
            (destination / entry.filename).chmod(stat.S_IMODE(mode))
PY

start_launcher="$unpacked_root/启动运营工具-macOS.command"
stop_launcher="$unpacked_root/停止运营工具-macOS.command"
[[ -x "$start_launcher" && -x "$stop_launcher" ]] || fail "解压包缺少可执行 macOS 启停入口"
extension_version="$(
  "$python_bin" - "$unpacked_root/apps/extension/manifest.json" <<'PY'
import json
from pathlib import Path
import sys

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
version = manifest.get("version")
if not isinstance(version, str) or not version:
    raise SystemExit("extension manifest has no version")
print(version)
PY
)" || fail "解压包缺少有效的扩展版本"
[[ "$extension_version" == "$expected_extension_version" ]] ||
  fail "扩展版本不符合验收目标：$extension_version"

export PORTABLE_COMPOSE_PROJECT="$project_name"
export API_PORT="$api_port"
export WEB_PORT="$web_port"
export POSTGRES_PORT="$postgres_port"
export S3_PORT="$s3_port"
export S3_CONSOLE_PORT="$s3_console_port"
export NEXT_PUBLIC_API_URL="http://127.0.0.1:${api_port}"
export WEB_ORIGIN="http://127.0.0.1:${web_port}"
export PORTABLE_NO_OPEN="1"
export IMAGE_TAG="$project_name"
export S3_PUBLIC_ENDPOINT="http://127.0.0.1:${s3_port}"

run_unpacked_launcher() {
  bash "$start_launcher"
}

wait_for_url() {
  local url="$1"
  local label="$2"
  local attempt
  for attempt in $(seq 1 60); do
    if curl --fail --silent --output /dev/null "$url"; then
      return 0
    fi
    sleep 1
  done
  fail "$label 未在 60 秒内就绪"
}

verify_one_shots() {
  local service container_id exit_code
  for service in migrate bucket-init demo-seed; do
    container_id="$(compose --profile demo ps -a -q "$service")"
    [[ -n "$container_id" ]] || fail "一次性任务 $service 不存在"
    exit_code="$(docker inspect --format '{{.State.ExitCode}}' "$container_id")"
    [[ "$exit_code" == "0" ]] || fail "一次性任务 $service 退出码为 $exit_code"
  done
}

assert_file_absent() {
  [[ ! -e "$1" ]] || fail "启动器创建了禁止的本地凭据文件"
}

json_field() {
  "$python_bin" - "$1" "$2" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    value = json.load(stream).get(sys.argv[2])
if not isinstance(value, str) or not value:
    raise SystemExit(f"missing JSON field: {sys.argv[2]}")
print(value)
PY
}

restricted_file() {
  install -m 600 /dev/null "$1"
}

admin_cookie_jar="$temporary_root/admin.cookies"
editor_cookie_jar="$temporary_root/editor.cookies"
admin_csrf_file="$temporary_root/admin-csrf.curl"
onboard_request="$temporary_root/onboard-request.json"
onboard_response="$temporary_root/onboard-response.json"
invite_response="$temporary_root/editor-invite-response.json"
editor_login_request="$temporary_root/editor-login-request.json"
editor_login_response="$temporary_root/editor-login-response.json"
editor_context_response="$temporary_root/editor-context-response.json"
account_request="$temporary_root/account-request.json"
account_response="$temporary_root/account-response.json"
content_request="$temporary_root/content-request.json"
content_response="$temporary_root/content-response.json"
members_response="$temporary_root/members-response.json"
accounts_response="$temporary_root/accounts-response.json"
contents_response="$temporary_root/contents-response.json"
for credential_file in \
  "$admin_cookie_jar" \
  "$editor_cookie_jar" \
  "$admin_csrf_file" \
  "$onboard_request" \
  "$onboard_response" \
  "$invite_response" \
  "$editor_login_request" \
  "$editor_login_response" \
  "$editor_context_response" \
  "$account_request" \
  "$account_response" \
  "$content_request" \
  "$content_response" \
  "$members_response" \
  "$accounts_response" \
  "$contents_response"; do
  restricted_file "$credential_file"
done
chmod 600 "$admin_cookie_jar" "$editor_cookie_jar" "$admin_csrf_file"

run_unpacked_launcher
verify_one_shots
wait_for_url "http://127.0.0.1:${api_port}/health/ready" "API"
wait_for_url "http://127.0.0.1:${web_port}/enter" "Web /enter"
assert_file_absent "$unpacked_root/.local-state/bootstrap.json"
assert_file_absent "$unpacked_root/.local-state/首次登录信息.txt"

printf '%s' '{"workspace_name":"合成本地验收团队","display_name":"合成管理员"}' >"$onboard_request"
curl --fail --silent --show-error \
  --request POST \
  --header "Content-Type: application/json" \
  --cookie-jar "$admin_cookie_jar" \
  --data-binary "@$onboard_request" \
  --output "$onboard_response" \
  "http://127.0.0.1:${api_port}/v1/workspaces/onboard"

workspace_id="$(json_field "$onboard_response" workspace_id)"
owner_member_id="$(json_field "$onboard_response" member_id)"
"$python_bin" - "$onboard_response" "$admin_csrf_file" <<'PY'
import json
from pathlib import Path
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    token = json.load(stream)["csrf_token"]
Path(sys.argv[2]).write_text(
    f'header = "X-CSRF-Token: {token}"\n',
    encoding="utf-8",
)
PY
chmod 600 "$admin_csrf_file"

curl --fail --silent --show-error \
  --request POST \
  --config "$admin_csrf_file" \
  --header "Content-Type: application/json" \
  --cookie "$admin_cookie_jar" \
  --data-binary '{"role":"editor"}' \
  --output "$invite_response" \
  "http://127.0.0.1:${api_port}/v1/workspaces/${workspace_id}/members/codes"

"$python_bin" - "$invite_response" "$editor_login_request" <<'PY'
import json
from pathlib import Path
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    code = json.load(stream)["code"]
Path(sys.argv[2]).write_text(
    json.dumps(
        {"code": code, "display_name": "合成编辑者"},
        ensure_ascii=False,
        separators=(",", ":"),
    ),
    encoding="utf-8",
)
PY
chmod 600 "$editor_login_request"
curl --fail --silent --show-error \
  --request POST \
  --header "Content-Type: application/json" \
  --cookie-jar "$editor_cookie_jar" \
  --data-binary "@$editor_login_request" \
  --output "$editor_login_response" \
  "http://127.0.0.1:${api_port}/v1/sessions/invite"
editor_member_id="$(json_field "$editor_login_response" member_id)"
curl --fail --silent --show-error \
  --cookie "$editor_cookie_jar" \
  --output "$editor_context_response" \
  "http://127.0.0.1:${api_port}/v1/workspaces/${workspace_id}/workbench/context"
"$python_bin" - "$editor_context_response" "$workspace_id" "$editor_member_id" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    context = json.load(stream)
assert context["workspace_id"] == sys.argv[2]
assert context["member_id"] == sys.argv[3]
assert context["role"] == "editor"
PY

printf '%s' '{"platform":"douyin","name":"合成账号","objectives":["内容验证"],"metric_weights":{"views":1.0},"benchmark_sample_size":5}' >"$account_request"
curl --fail --silent --show-error \
  --request POST \
  --config "$admin_csrf_file" \
  --header "Content-Type: application/json" \
  --cookie "$admin_cookie_jar" \
  --data-binary "@$account_request" \
  --output "$account_response" \
  "http://127.0.0.1:${api_port}/v1/workspaces/${workspace_id}/accounts"
account_id="$(json_field "$account_response" id)"

"$python_bin" - "$content_request" "$workspace_id" "$account_id" <<'PY'
import json
from pathlib import Path
import sys

payload = {
    "workspace_id": sys.argv[2],
    "account_id": sys.argv[3],
    "platform": "douyin",
    "content_type": "video",
    "title": "合成本地持久化内容",
    "body": "仅用于隔离便携包验收。",
}
Path(sys.argv[1]).write_text(
    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    encoding="utf-8",
)
PY
chmod 600 "$content_request"
curl --fail --silent --show-error \
  --request POST \
  --config "$admin_csrf_file" \
  --header "Content-Type: application/json" \
  --cookie "$admin_cookie_jar" \
  --data-binary "@$content_request" \
  --output "$content_response" \
  "http://127.0.0.1:${api_port}/v1/contents"
content_id="$(json_field "$content_response" id)"

fetch_persisted_state() {
  curl --fail --silent --show-error \
    --cookie "$admin_cookie_jar" \
    --output "$members_response" \
    "http://127.0.0.1:${api_port}/v1/workspaces/${workspace_id}/members"
  curl --fail --silent --show-error \
    --cookie "$admin_cookie_jar" \
    --output "$accounts_response" \
    "http://127.0.0.1:${api_port}/v1/workspaces/${workspace_id}/accounts"
  curl --fail --silent --show-error \
    --cookie "$admin_cookie_jar" \
    --output "$contents_response" \
    "http://127.0.0.1:${api_port}/v1/contents?workspace_id=${workspace_id}"
}

verify_persisted_fixture() {
  "$python_bin" - \
    "$members_response" \
    "$accounts_response" \
    "$contents_response" \
    "$workspace_id" \
    "$owner_member_id" \
    "$editor_member_id" \
    "$account_id" \
    "$content_id" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    members = json.load(stream)
with open(sys.argv[2], encoding="utf-8") as stream:
    accounts = json.load(stream)
with open(sys.argv[3], encoding="utf-8") as stream:
    contents = json.load(stream)
workspace_id, owner_id, editor_id, account_id, content_id = sys.argv[4:]
assert len(members) == 2
assert {item["id"] for item in members} == {owner_id, editor_id}
assert all(item["workspace_id"] == workspace_id for item in members)
assert [item["id"] for item in accounts] == [account_id]
assert all(item["workspace_id"] == workspace_id for item in accounts)
assert [item["id"] for item in contents] == [content_id]
assert all(item["workspace_id"] == workspace_id for item in contents)
print(len(members))
PY
}

fetch_persisted_state
member_count_before_restart="$(verify_persisted_fixture)"

bash "$stop_launcher"
assert_file_absent "$unpacked_root/.local-state/bootstrap.json"
assert_file_absent "$unpacked_root/.local-state/首次登录信息.txt"
run_unpacked_launcher
verify_one_shots
fetch_persisted_state
member_count_after_restart="$(verify_persisted_fixture)"

run_unpacked_launcher
verify_one_shots
fetch_persisted_state
member_count_after_second_start="$(verify_persisted_fixture)"
[[ "$member_count_before_restart" == "$member_count_after_restart" ]] ||
  fail "重启后成员数量发生变化"
[[ "$member_count_before_restart" == "$member_count_after_second_start" ]] ||
  fail "二次启动后成员数量发生变化"
assert_file_absent "$unpacked_root/.local-state/bootstrap.json"
assert_file_absent "$unpacked_root/.local-state/首次登录信息.txt"

cleanup_resources || fail "隔离 Docker 资源未完全清理"
cleanup_done=1
finished_at="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
evidence_path="$(dirname "$zip_path")/portable-acceptance.json"
evidence_tmp="${evidence_path}.tmp"

# EVIDENCE_START
SCHEMA_VERSION="operations-ai-portable-acceptance/v1" \
MACOS_RUNTIME="passed" \
SOURCE_COMMIT="$source_commit" \
ZIP_SHA256="$zip_sha256" \
EXTENSION_VERSION="$extension_version" \
STARTED_AT="$started_at" \
FINISHED_AT="$finished_at" \
DOCKER_VERSION="$docker_version" \
DOCKER_COMPOSE_VERSION="$docker_compose_version" \
WORKSPACE_ID="$workspace_id" \
OWNER_MEMBER_ID="$owner_member_id" \
EDITOR_MEMBER_ID="$editor_member_id" \
ACCOUNT_ID="$account_id" \
CONTENT_ID="$content_id" \
MEMBER_COUNT="$member_count_after_second_start" \
CLEANUP="passed" \
"$python_bin" - "$evidence_tmp" "$evidence_allowed_fields" <<'PY'
import json
import os
from pathlib import Path
import sys

payload = {
    "schema_version": os.environ["SCHEMA_VERSION"],
    "macos_runtime": os.environ["MACOS_RUNTIME"],
    "source_commit": os.environ["SOURCE_COMMIT"],
    "zip_sha256": os.environ["ZIP_SHA256"],
    "extension_version": os.environ["EXTENSION_VERSION"],
    "started_at": os.environ["STARTED_AT"],
    "finished_at": os.environ["FINISHED_AT"],
    "docker_version": os.environ["DOCKER_VERSION"],
    "docker_compose_version": os.environ["DOCKER_COMPOSE_VERSION"],
    "workspace_id": os.environ["WORKSPACE_ID"],
    "owner_member_id": os.environ["OWNER_MEMBER_ID"],
    "editor_member_id": os.environ["EDITOR_MEMBER_ID"],
    "account_id": os.environ["ACCOUNT_ID"],
    "content_id": os.environ["CONTENT_ID"],
    "member_count": int(os.environ["MEMBER_COUNT"]),
    "cleanup": os.environ["CLEANUP"],
}
allowed = set(sys.argv[2].split())
if set(payload) != allowed:
    raise SystemExit("portable acceptance evidence fields drifted")
Path(sys.argv[1]).write_text(
    json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
PY
# EVIDENCE_END
chmod 600 "$evidence_tmp"
mv "$evidence_tmp" "$evidence_path"

printf 'portable_acceptance=passed\n'
printf 'portable_zip_sha256=%s\n' "$zip_sha256"
printf 'portable_source_commit=%s\n' "$source_commit"
printf 'portable_evidence=%s\n' "$evidence_path"
