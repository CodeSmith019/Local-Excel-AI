@echo off
cd /d %~dp0..
set PROFILE=%1
if "%PROFILE%"=="" set PROFILE=dell
set EXAI_ENV_FILE=config\%PROFILE%.env

echo Using environment profile: %EXAI_ENV_FILE%
if not exist "%EXAI_ENV_FILE%" (
    echo Warning: %EXAI_ENV_FILE% not found!
)

uv run uvicorn backend.main:create_app --factory --host 127.0.0.1 --port 8000

