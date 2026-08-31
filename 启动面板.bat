@echo off
rem ============================================================
rem  一键启动面板守护（含 ComfyUI 控制口 + SSH 反向隧道）
rem  双击本脚本即可；无需再单独开「启动面板隧道.bat」
rem  守护进程用内嵌 pythonw.exe 无窗口运行，本窗口可关闭
rem ============================================================
title JT 面板守护
start "" "D:\ComfyUI_Mie\python_embeded\pythonw.exe" "D:\LAN-Share\lora\_work\comfy_panel\comfy_watchdog.py"
echo 面板守护已启动（无窗口后台运行）。
echo 关闭本窗口不影响守护运行。
timeout /t 2 /nobreak >nul
