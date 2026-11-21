@echo off
setlocal
title DSH Lazy Pack v5 Uninstaller
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" -Uninstall
echo.
echo Done. Restart DSH to take effect.
pause
