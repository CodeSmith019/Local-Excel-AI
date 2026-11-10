@echo off
cd /d %~dp0..

set PROFILE=%1
if "%PROFILE%"=="" set PROFILE=dell

set MODE=%2
if "%MODE%"=="" set MODE=http

echo ============================================================
echo   Excel AI - One-Click Startup
echo   Profile: %PROFILE% ^| Mode: %MODE%
echo ============================================================

rem 1. Check llama-server binary
if not exist "llama\llama-server.exe" (
    echo [ERROR] llama\llama-server.exe not found!
    exit /b 1
)

rem 2. Select model and context based on profile
if /i "%PROFILE%"=="yoga" (
    set MODEL_PATH=models\gpt-oss-20b-mxfp4.gguf
    set CTX_SIZE=8192
    if not exist "%MODEL_PATH%" (
        echo [WARN] %MODEL_PATH% not found, checking for Qwen fallback...
        set MODEL_PATH=models\Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf
    )
) else (
    set MODEL_PATH=models\Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf
    set CTX_SIZE=4096
)

if not exist "%MODEL_PATH%" (
    echo [ERROR] Model file %MODEL_PATH% not found!
    exit /b 1
)

rem 3. Start llama-server minimised
echo [1/4] Starting llama-server (%MODEL_PATH%, context %CTX_SIZE%) minimised...
start "llama-server" /min llama\llama-server.exe -m "%MODEL_PATH%" -ngl 99 -c %CTX_SIZE% --jinja --host 127.0.0.1 --port 8080

rem 4. Wait for llama-server /health (timeout 120s)
echo [2/4] Waiting for llama-server to be ready (up to 120s)...
.venv\Scripts\python.exe -c "import urllib.request, json, time, sys; t=time.time(); ok=False; exec('while time.time()-t < 120:\n try:\n  with urllib.request.urlopen(\'http://127.0.0.1:8080/health\', timeout=2) as r:\n   if json.loads(r.read().decode(\'utf-8\')).get(\'status\') == \'ok\': ok=True; break\n except Exception: pass\n time.sleep(2)'); sys.exit(0 if ok else 1)"
if errorlevel 1 (
    echo [ERROR] Timed out waiting for llama-server on http://127.0.0.1:8080/health!
    exit /b 1
)
echo [OK] llama-server is healthy!

rem 5. Start Backend
if /i "%MODE%"=="https" (
    echo [3/4] Starting FastAPI backend with HTTPS on port 8443...
    start "Excel AI Backend" scripts\start_backend_https.bat %PROFILE%
) else (
    echo [3/4] Starting FastAPI backend with HTTP on port 8000...
    start "Excel AI Backend" scripts\start_backend.bat %PROFILE%
)

rem Small delay to allow backend to initialize
timeout /t 3 /nobreak >nul

rem 6. Launch Microsoft Excel
echo [4/4] Opening Microsoft Excel...
if exist "C:\Program Files\Microsoft Office\Root\Office16\EXCEL.EXE" (
    start "" "C:\Program Files\Microsoft Office\Root\Office16\EXCEL.EXE"
) else if exist "C:\Program Files (x86)\Microsoft Office\Root\Office16\EXCEL.EXE" (
    start "" "C:\Program Files (x86)\Microsoft Office\Root\Office16\EXCEL.EXE"
) else (
    start excel.exe
)

echo ============================================================
echo   Excel AI is ready!
echo   - Model: 127.0.0.1:8080 (llama-server)
if /i "%MODE%"=="https" (
    echo   - Backend: https://localhost:8443 (task pane)
) else (
    echo   - Backend: http://127.0.0.1:8000 (browser mode)
)
echo   - Excel: Desktop app opened
echo   Run scripts\stop_all.bat to stop all services.
echo ============================================================
