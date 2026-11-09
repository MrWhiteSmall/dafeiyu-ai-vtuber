@echo off
chcp 65001 >nul
title 抖音弹幕监听 - 一键启动
cd /d "%~dp0"

set "EXE=%~dp0tools\DouyinBarrageGrab\WssBarrageServer.exe"
set "DIR=%~dp0tools\DouyinBarrageGrab"

if not exist "%EXE%" (
  echo [X] 找不到弹幕程序：
  echo     %EXE%
  echo     请确认 tools\DouyinBarrageGrab 目录存在。
  pause
  exit /b 1
)

echo.
echo  ================================
echo   抖音弹幕监听 一键启动
echo  ================================
echo.

tasklist /fi "imagename eq WssBarrageServer.exe" 2>nul | find /i "WssBarrageServer.exe" >nul
if not errorlevel 1 (
  echo [i] 弹幕程序已经在运行了，不用重复启动。
  goto :checkport
)

echo [1/3] 正在申请管理员权限...  请在弹出的 UAC 窗口点【是】
wscript //nologo "%~dp0tools\_runas.vbs" "%DIR%" "%EXE%"
if errorlevel 1 (
  echo [X] 提权被取消，或者被系统拦截了。
  echo     备用办法：右键 WssBarrageServer.exe - 以管理员身份运行
  pause
  exit /b 1
)

timeout /t 4 >nul

:checkport
echo [2/3] 检查监听端口 8888 ...
set "OK="
for /l %%i in (1,1,10) do (
  netstat -ano | findstr ":8888" | findstr "LISTENING" >nul && (set "OK=1" & goto :up)
  timeout /t 1 >nul
)
:up
if not defined OK (
  echo [X] 8888 端口没起来。可能没点 UAC 的【是】，或者被安全软件拦了。
  pause
  exit /b 1
)
echo [OK] 8888 端口已监听，弹幕程序在正常工作。

echo.
echo [3/3] 接下来请在那个弹幕程序窗口里：
echo       1. 粘贴你的直播间地址（形如 https://live.douyin.com/123456789）
echo       2. 如果提示装证书，点【是 / 信任】
echo       3. 点【开始】/【连接】，等到窗口里开始滚弹幕
echo.
echo  弹幕滚起来了，再去双击 启动大肥鱼（先跑弹幕程序）.bat
echo.
echo  注意：关掉弹幕程序后如果上不了网，
echo        去 设置 - 网络和 Internet - 代理，关掉「使用代理服务器」。
echo.
pause