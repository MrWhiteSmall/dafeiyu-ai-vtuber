@echo off
chcp 65001 >nul
title 大肥鱼 UI 助手 - 请勿关闭
cd /d "%~dp0"
echo.
echo  ============================================
echo   UI 助手（管理员权限）
echo  ============================================
echo.
echo  这个窗口是用来帮你点直播伴侣的，请挂着别关。
echo  等我在旁边给你下指令就行。
echo.
wscript //nologo "%~dp0tools\_runas2.vbs" "powershell.exe" "-NoProfile -ExecutionPolicy Bypass -File \"%~dp0out\ui_agent.ps1\"" "%~dp0"
timeout /t 2 >nul
echo 已发起提权请求，请在 UAC 窗口点【是】。
timeout /t 5 >nul