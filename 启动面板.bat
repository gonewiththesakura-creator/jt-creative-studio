@echo off
rem ============================================================
rem  一键启动面板守护（含 ComfyUI 控制口 + SSH 反向隧道）
rem  双击本脚本即可；无需再单独开「启动面板隧道.bat」
rem  PowerShell helper 校验合同后复用或无窗口重启守护，本窗口可关闭
rem ============================================================
title JT 面板守护
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\start_comfy_watchdog.ps1"
if errorlevel 1 (
    echo 面板守护启动失败，请保留本窗口并检查上方错误。
    pause
    exit /b 1
)
echo 面板守护合同已验证，可关闭本窗口。
timeout /t 2 /nobreak >nul
