@echo off
REM GB28181 Analyzer - dev launcher (backend + frontend)
title GB28181 Analyzer - Dev
cd /d "%~dp0"

echo [1/2] Starting backend on :8788 ...
start "GB28181 Backend" cmd /k "cd /d %~dp0backend && .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8788 --reload"

timeout /t 4 /nobreak >nul

echo [2/2] Starting frontend on :5173 ...
start "GB28181 Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

timeout /t 5 /nobreak >nul
start http://localhost:5173

echo.
echo   Backend  : http://127.0.0.1:8788/api/v1/docs
echo   Frontend : http://localhost:5173
echo.
echo Close the two windows to stop.
pause
