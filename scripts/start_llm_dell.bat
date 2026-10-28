@echo off
cd /d %~dp0..
llama\llama-server.exe -m models\Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf -ngl 99 -c 4096 --jinja --host 127.0.0.1 --port 8080

