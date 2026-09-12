@echo off
chcp 65001 >nul
rem 一键注入 WorkBuddy 破甲（双击即用）。还原：install-workbuddy.cmd -Uninstall
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-workbuddy.ps1" %*
echo.
pause
