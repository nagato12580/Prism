@echo off
chcp 65001 >nul
echo ============================================================
echo   停止 Prism (AIOne) 服务
echo ============================================================

REM 按端口杀掉监听进程：5175=Backend, 5180=Engine, 5173=Frontend
for %%P in (5175 5180 5173) do (
    set "FOUND="
    for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":%%P" ^| findstr "LISTENING"') do (
        taskkill /PID %%a /F >nul 2>nul
        if not errorlevel 1 (
            echo   已停止端口 %%P 上的进程 (PID %%a)
            set "FOUND=1"
        )
    )
    if not defined FOUND echo   端口 %%P 无监听进程
)

echo.
echo 完成。
pause
