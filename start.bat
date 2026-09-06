@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title TCMS × AI 测试平台
cd /d "%~dp0"

REM 端口（可 set PORT=8001 覆盖）
if not defined PORT set "PORT=8000"

echo.
echo  ============================================
echo   TCMS × AI 测试平台  一键启动
echo  ============================================
echo.

REM ---- 1. 定位 Python ----
set "PY=python"
where python >nul 2>&1
if errorlevel 1 (
  echo  [✗] 未找到 python。请先安装 Python 3.11+：https://www.python.org/downloads/
  echo       安装时勾选 "Add Python to PATH"。
  pause & exit /b 1
)

REM ---- 2. 建虚拟环境 ----
if not exist ".venv\Scripts\python.exe" (
  echo  [1/4] 首次运行：创建虚拟环境 .venv ...
  python -m venv .venv
  if errorlevel 1 ( echo  [✗] venv 创建失败 & pause & exit /b 1 )
)

set "PYV=.venv\Scripts\python.exe"

REM ---- 3. 装依赖 ----
"%PYV%" -c "import fastapi, uvicorn, cantools, yaml, numpy" >nul 2>&1
if errorlevel 1 (
  echo  [2/4] 安装依赖 ^(首次较慢^)...
  "%PYV%" -m pip install --upgrade pip -q
  "%PYV%" -m pip install -e . -q
  if errorlevel 1 ( echo  [✗] 依赖安装失败 & pause & exit /b 1 )
) else (
  echo  [2/4] 依赖已就绪
)

REM ---- 4. 可选：TCMS 引擎（场景执行/Agent 需要）----
"%PYV%" -c "import tcms" >nul 2>&1
if errorlevel 1 (
  if defined TCMS_UPSTREAM_DIR (
    echo  [3/4] 使用 TCMS_UPSTREAM_DIR=%TCMS_UPSTREAM_DIR%
  ) else if exist "..\tcms-can-test\tcms" (
    echo  [3/4] 发现兄弟目录 tcms-can-test，将作为上游引擎
  ) else (
    echo  [3/4] 未发现 TCMS 引擎。安装可用的 tcms-can-test ...
    echo         - 若需完整场景执行/Agent 功能，建议安装：
    "%PYV%" -m pip install -e ".[upstream]" -q 2>nul
    if errorlevel 1 echo         (安装失败可稍后手动执行: pip install -e ".[upstream]")
  )
) else (
  echo  [3/4] TCMS 引擎已就绪
)

REM ---- 5. 启动 ----
echo  [4/4] 启动服务 → http://127.0.0.1:8000
echo.
echo  提示：浏览器会自动打开。关闭本窗口即停止服务。
echo  如端口被占：set PORT=8001 后重新运行。
echo.

REM 自动开浏览器（延迟 2 秒等服务起来）
start "" /b cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:%PORT%"

"%PYV%" -m uvicorn tcms_ai_platform.server.app:app --host 127.0.0.1 --port %PORT%

pause
