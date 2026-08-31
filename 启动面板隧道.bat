@echo off
rem ============================================================
rem  ComfyUI 面板隧道（开机/双击运行）
rem  服务器 127.0.0.1:8199 -> 本机 ComfyUI 127.0.0.1:8188
rem  需要先启动 ComfyUI（1_1点击启动comfyui.bat），再运行本脚本
rem ============================================================
title JT ComfyUI 面板隧道
cd /d D:\LAN-Share\lora\_work\comfy_panel\tools
:loop
ssh -i id_ed25519 -N -R 8199:127.0.0.1:8188 -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -o StrictHostKeyChecking=accept-new admin@8.210.125.65
echo [%date% %time%] 隧道断开，5 秒后重连...
timeout /t 5 /nobreak >nul
goto loop
