@echo off
echo Stopping Excel AI background services...

rem Kill llama-server
taskkill /F /IM llama-server.exe >nul 2>&1
if not errorlevel 1 (
    echo   [OK] Stopped llama-server
) else (
    echo   [INFO] llama-server was not running
)

rem Kill uvicorn
taskkill /F /IM uvicorn.exe >nul 2>&1
if not errorlevel 1 (
    echo   [OK] Stopped uvicorn backend
) else (
    echo   [INFO] uvicorn was not running
)

rem Kill any command prompt windows started by start_all
taskkill /F /FI "WINDOWTITLE eq Excel AI Backend*" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq llama-server*" >nul 2>&1

echo All Excel AI services have been stopped.

