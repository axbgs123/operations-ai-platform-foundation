@echo off
setlocal EnableExtensions DisableDelayedExpansion

set "ROOT_DIR=%~dp0.."
if not defined PORTABLE_COMPOSE_PROJECT set "PORTABLE_COMPOSE_PROJECT=operations-ai-local"

docker compose --project-name "%PORTABLE_COMPOSE_PROJECT%" --env-file "%ROOT_DIR%\.env" -f "%ROOT_DIR%\infra\docker\compose.yml" --profile demo down
if errorlevel 1 (
  echo 停止失败：请确认 Docker Desktop 正在运行。 1>&2
  exit /b 1
)

echo 运营工具已停止，本地数据卷保持不变。
exit /b 0
