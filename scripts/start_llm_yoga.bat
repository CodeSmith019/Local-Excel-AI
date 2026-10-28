@echo off
cd /d %~dp0..
if /i "%1"=="qwen" (
    echo Starting llama-server with Qwen2.5-Coder-7B-Instruct (parity mode, context 8192)...
    llama\llama-server.exe -m models\Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf -ngl 99 -c 8192 --jinja --host 127.0.0.1 --port 8080
) else (
    echo Starting llama-server with gpt-oss-20b-mxfp4 (context 8192)...
    llama\llama-server.exe -m models\gpt-oss-20b-mxfp4.gguf -ngl 99 -c 8192 --jinja --host 127.0.0.1 --port 8080
)

