@echo off
title DataCrab
cd /d "%~dp0"
"runtime\python.exe" "launcher.py"
echo.
echo [DataCrab] 服务已停止。
pause
