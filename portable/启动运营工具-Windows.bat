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

set "STATE_DIR=%ROOT_DIR%\.local-state"
set "BOOTSTRAP_FILE=%STATE_DIR%\bootstrap.json"
set "BOOTSTRAP_TMP=%STATE_DIR%\bootstrap.json.tmp"
set "LOGIN_FILE=%STATE_DIR%\首次登录信息.txt"
set "ENTRY_URL=http://127.0.0.1:%WEB_PORT%/enter"
if not exist "%STATE_DIR%" mkdir "%STATE_DIR%"
if errorlevel 1 (
  echo 启动失败：无法创建本机状态目录。 1>&2
  popd
  exit /b 1
)

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

if not exist "%BOOTSTRAP_FILE%" (
  if exist "%BOOTSTRAP_TMP%" del /Q "%BOOTSTRAP_TMP%" >nul 2>&1
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$body=@{name='本地运营工作区'} | ConvertTo-Json -Compress; $response=Invoke-RestMethod -Method Post -Uri ('http://127.0.0.1:'+$env:API_PORT+'/v1/workspaces') -ContentType 'application/json' -Body $body; if ([string]::IsNullOrWhiteSpace([string]$response.workspace_id) -or [string]::IsNullOrWhiteSpace([string]$response.admin_code)) { throw 'invalid bootstrap response' }; $validated=[ordered]@{workspace_id=[string]$response.workspace_id; admin_code=[string]$response.admin_code}; $json=$validated | ConvertTo-Json -Compress; [IO.File]::WriteAllText($env:BOOTSTRAP_TMP,$json,(New-Object Text.UTF8Encoding($false))); Move-Item -LiteralPath $env:BOOTSTRAP_TMP -Destination $env:BOOTSTRAP_FILE -Force"
  if errorlevel 1 (
    if exist "%BOOTSTRAP_TMP%" del /Q "%BOOTSTRAP_TMP%" >nul 2>&1
    echo 工作区初始化失败，服务仍在运行。重试命令：set PORTABLE_NO_OPEN=1 ^& "%~f0" 1>&2
    popd
    exit /b 1
  )
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "$data=Get-Content -LiteralPath $env:BOOTSTRAP_FILE -Raw -Encoding UTF8 | ConvertFrom-Json; if ([string]::IsNullOrWhiteSpace([string]$data.workspace_id) -or [string]::IsNullOrWhiteSpace([string]$data.admin_code)) { throw 'invalid bootstrap state' }; $lines=@('运营内容智能分析与生成平台',('私有入口：'+$env:ENTRY_URL),('工作区 ID：'+[string]$data.workspace_id),('管理员邀请码：'+[string]$data.admin_code),'','此文件包含一次性敏感信息。首次登录后请妥善保管。'); [IO.File]::WriteAllLines($env:LOGIN_FILE,$lines,(New-Object Text.UTF8Encoding($false))); if (Get-Command Set-Clipboard -ErrorAction SilentlyContinue) { Set-Clipboard -Value ([string]$data.admin_code) }"
if errorlevel 1 (
  echo 启动失败：本机初始化状态无效，未创建新工作区。 1>&2
  popd
  exit /b 1
)

echo 运营工具已就绪：%ENTRY_URL%
echo 首次登录信息已安全写入本机 .local-state 目录。
if not "%PORTABLE_NO_OPEN%"=="1" (
  start "" "http://127.0.0.1:%WEB_PORT%/enter"
  if errorlevel 1 echo 未能自动打开浏览器，请手动访问：%ENTRY_URL% 1>&2
)

popd
exit /b 0
