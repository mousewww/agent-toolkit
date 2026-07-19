@echo off
REM start_headroom.bat — 启动 Headroom 本地压缩代理
REM
REM 用法：
REM   .\scripts\start_headroom.bat [port]
REM
REM 启动后，设置环境变量即可让所有 LLM 调用自动走压缩：
REM   set HEADROOM_PROXY_URL=http://localhost:8787/v1

set PORT=%~1
if "%PORT%"=="" set PORT=8787

echo Starting Headroom proxy on port %PORT%...
echo Set HEADROOM_PROXY_URL=http://localhost:%PORT%/v1 in your environment.

headroom proxy --port %PORT%
