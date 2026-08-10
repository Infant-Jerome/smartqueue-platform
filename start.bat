@echo off
setlocal
echo Starting SmartQueue Platform...
echo.

echo [0/2] Freeing ports 8000 and 5173...
for %%P in (8000 5173) do (
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr "LISTENING" ^| findstr ":%%P "') do (
        taskkill /F /PID %%a >nul 2>&1
    )
)
ping -n 2 127.0.0.1 >nul

echo [1/2] Starting backend (FastAPI on http://localhost:8000)...
start "SmartQueue Backend" cmd /k "cd /d %~dp0backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"

echo [2/2] Starting frontend (Vite on http://localhost:5173)...
start "SmartQueue Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

echo.
echo Done. Backend: http://localhost:8000 (docs at /docs)
echo Frontend: http://localhost:5173
echo Close the two windows to stop the servers.
endlocal