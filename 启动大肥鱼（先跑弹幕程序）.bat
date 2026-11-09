@echo off
chcp 65001 >nul
title 大肥鱼 · 启动主程序
cd /d "%~dp0"
set "PATH=%~dp0tools\ffmpeg\bin;%PATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

echo ================================================
echo   大肥鱼 AI 虚拟主播 - 启动
echo   注意：请先以管理员身份运行
echo   tools\DouyinBarrageGrab\WssBarrageServer.exe
echo ================================================
echo.

echo [1/4] 检查大模型兜底代理（端口 8787）...
powershell -NoProfile -Command "try{(Invoke-WebRequest 'http://127.0.0.1:8787/health' -UseBasicParsing -TimeoutSec 2).StatusCode|Out-Null; exit 0}catch{exit 1}"
if errorlevel 1 (
  start "大模型兜底代理" /min "%~dp0.venv\Scripts\python.exe" -u "%~dp0tools\llm_fallback.py"
  echo       已启动（DeepSeek 优先，超时自动换 qwen-flash）
  timeout /t 3 >nul
) else (
  echo       已在运行，跳过
)

echo [2/4] 检查字幕服务（端口 5500）...
powershell -NoProfile -Command "try{(Invoke-WebRequest 'http://127.0.0.1:5500/health' -UseBasicParsing -TimeoutSec 2).StatusCode|Out-Null; exit 0}catch{exit 1}"
if errorlevel 1 (
  start "字幕服务" /min "%~dp0.venv\Scripts\python.exe" -u "%~dp0tools\caption_printer.py"
  echo       已启动
) else (
  echo       已在运行，跳过
)

echo [3/4] 检查口型服务（out\songroom\mouth.json）...
if exist "%~dp0out\songroom\lipsync.pid" (
  echo       已在运行，跳过
) else (
  start "口型服务" /min "%~dp0.venv\Scripts\python.exe" -u "%~dp0tools\songroom_lipsync.py"
  echo       已启动
)

echo [4/4] 启动主程序（8082 / Live2D 12345）...
start "大肥鱼主程序" "%~dp0.venv\Scripts\python.exe" -u "%~dp0main.py"

echo.
echo 主程序正在启动，大约 10 秒后 Live2D 画面可用：
echo   http://127.0.0.1:12345/Live2D/stage-portrait.html
echo.
echo 接着：打开 OBS -^> 点「启动虚拟摄像头」-^> 打开直播伴侣开播
echo 本窗口 5 秒后自动关闭
timeout /t 5 >nul
