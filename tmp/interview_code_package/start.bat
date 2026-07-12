@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo   Prism (AIOne)  一键启动
echo ============================================================

REM ---------- 1. Python 虚拟环境 + 依赖 ----------
if not exist ".venv\Scripts\python.exe" (
    echo [setup] 创建虚拟环境 .venv ...
    py -3.12 -m venv .venv 2>nul
    if errorlevel 1 python -m venv .venv
)

".venv\Scripts\python.exe" -c "import fastapi, uvicorn, pymilvus, sqlalchemy" >nul 2>nul
if errorlevel 1 (
    echo [setup] 首次启动，正在安装 Python 依赖（requirements.txt）...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [error] Python 依赖安装失败，请检查网络或手动执行: .venv\Scripts\python.exe -m pip install -r requirements.txt
        pause & exit /b 1
    )
)

REM ---------- 2. 前端依赖 ----------
if not exist "frontend\node_modules\vite\bin\vite.js" (
    echo [setup] 首次启动，正在安装前端依赖...
    pushd frontend
    where pnpm >nul 2>nul && (call pnpm install) || (call npx --yes pnpm install)
    popd
)

REM ---------- 3. 启动 Backend（会自动拉起 Engine）----------
echo [run] 启动 Backend :5175 （自动拉起 Engine :5180）...
start "Prism Backend" cmd /k "cd /d %~dp0 && .venv\Scripts\python.exe -m backend.run"

REM ---------- 4. 启动 Frontend ----------
echo [run] 启动 Frontend :5173 ...
start "Prism Frontend" cmd /k "cd /d %~dp0\frontend && node node_modules\vite\bin\vite.js"

REM ---------- 5. 等待就绪后打开浏览器 ----------
echo.
echo [wait] 等待服务就绪（约 10 秒）...
timeout /t 10 >nul
start http://localhost:5173

echo.
echo ============================================================
echo   启动完成！
echo     前端 Frontend :  http://localhost:5173
echo     后端 Backend   :  http://localhost:5175/health
echo     引擎 Engine     :  http://localhost:5180/health
echo   关闭服务：关闭弹出的两个窗口，或运行 stop.bat
echo ============================================================
echo.
echo 提示：后端窗口首次启动需连接云服务器（MySQL/Milvus/ES），
echo       若长时间卡住请确认 .env 中的 CLOUD_IP 可达。
pause
endlocal
