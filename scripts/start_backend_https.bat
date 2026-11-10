@echo off
cd /d %~dp0..
set PROFILE=%1
if "%PROFILE%"=="" set PROFILE=dell
set EXAI_ENV_FILE=config\%PROFILE%.env

set CERT_FILE=%USERPROFILE%\.office-addin-dev-certs\localhost.crt
set KEY_FILE=%USERPROFILE%\.office-addin-dev-certs\localhost.key

if not exist "%CERT_FILE%" (
    echo [ERROR] SSL certificate not found at %CERT_FILE%
    echo Please run: npx office-addin-dev-certs install
    exit /b 1
)

if not exist "%KEY_FILE%" (
    echo [ERROR] SSL private key not found at %KEY_FILE%
    echo Please run: npx office-addin-dev-certs install
    exit /b 1
)

set EXAI_BACKEND_PORT=8443
set EXAI_SSL_CERTFILE=%CERT_FILE%
set EXAI_SSL_KEYFILE=%KEY_FILE%

echo Using environment profile: %EXAI_ENV_FILE%
if not exist "%EXAI_ENV_FILE%" (
    echo Warning: %EXAI_ENV_FILE% not found!
)
echo Starting HTTPS backend on https://localhost:8443 ...

uv run uvicorn backend.main:create_app --factory --host localhost --port 8443 --ssl-keyfile "%KEY_FILE%" --ssl-certfile "%CERT_FILE%"

