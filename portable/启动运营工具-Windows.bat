@echo off
setlocal EnableExtensions DisableDelayedExpansion

set "ROOT_DIR=%~dp0.."
pushd "%ROOT_DIR%" >nul 2>&1
if errorlevel 1 (
  echo 启动失败：无法定位安装目录。 1>&2
  exit /b 1
)

where docker >nul 2>&1
if errorlevel 1 (
  echo 启动失败：未找到 Docker，请先安装并启动 Docker Desktop。 1>&2
  popd
  exit /b 1
)
docker info >nul 2>&1
if errorlevel 1 (
  echo 启动失败：Docker Desktop 未运行，请启动后重试。 1>&2
  popd
  exit /b 1
)
docker compose version >nul 2>&1
if errorlevel 1 (
  echo 启动失败：需要 Docker Compose v2。 1>&2
  popd
  exit /b 1
)

if not exist .env copy /Y .env.example .env >nul
if errorlevel 1 (
  echo 启动失败：无法从 .env.example 创建本地 .env。 1>&2
  popd
  exit /b 1
)
if not defined PORTABLE_COMPOSE_PROJECT set "PORTABLE_COMPOSE_PROJECT=operations-ai-local"
if not defined API_PORT set "API_PORT=8000"
if not defined WEB_PORT set "WEB_PORT=3000"
if not defined PORTABLE_NO_OPEN set "PORTABLE_NO_OPEN=0"
set "ENTRY_URL=http://127.0.0.1:%WEB_PORT%/enter"

echo 正在启动服务，首次构建可能需要 5-15 分钟……
docker compose --project-name "%PORTABLE_COMPOSE_PROJECT%" --env-file "%ROOT_DIR%\.env" -f "%ROOT_DIR%\infra\docker\compose.yml" --profile demo up -d --build
if errorlevel 1 (
  echo 启动失败：Docker Compose 启动失败。已有数据卷已保留，可重试本脚本。 1>&2
  popd
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "$deadline=(Get-Date).AddSeconds(120); do { try { $response=Invoke-WebRequest -UseBasicParsing -Uri ('http://127.0.0.1:'+$env:API_PORT+'/health/ready') -TimeoutSec 5; if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) { exit 0 } } catch {}; Start-Sleep -Seconds 1 } while ((Get-Date) -lt $deadline); exit 1"
if errorlevel 1 (
  echo 启动失败：API 在 120 秒内未就绪。 1>&2
  echo 诊断命令：docker compose --project-name "%PORTABLE_COMPOSE_PROJECT%" --env-file "%ROOT_DIR%\.env" -f "%ROOT_DIR%\infra\docker\compose.yml" ps 1>&2
  popd
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "$deadline=(Get-Date).AddSeconds(60); do { try { $response=Invoke-WebRequest -UseBasicParsing -Uri $env:ENTRY_URL -TimeoutSec 5; if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) { exit 0 } } catch {}; Start-Sleep -Seconds 1 } while ((Get-Date) -lt $deadline); exit 1"
if errorlevel 1 (
  echo 启动失败：Web 私有入口在 60 秒内未就绪。 1>&2
  echo 诊断命令：docker compose --project-name "%PORTABLE_COMPOSE_PROJECT%" --env-file "%ROOT_DIR%\.env" -f "%ROOT_DIR%\infra\docker\compose.yml" logs --tail=100 api web 1>&2
  popd
  exit /b 1
)

echo 运营工具已就绪：%ENTRY_URL%
if not "%PORTABLE_NO_OPEN%"=="1" (
  start "" "http://127.0.0.1:%WEB_PORT%/enter"
  if errorlevel 1 echo 未能自动打开浏览器，请手动访问：%ENTRY_URL% 1>&2
)

popd
exit /b 0
