@echo off
chcp 65001 >nul
echo Starting DataCrab backend (port 8000)...
start "DataCrab-Backend" /MIN cmd /k "cd /d d:\DataCrab\backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"
echo Starting DataCrab frontend (port 5173)...
start "DataCrab-Frontend" /MIN cmd /k "cd /d d:\DataCrab\frontend && npm run dev"
echo Both services launched in minimized windows.
