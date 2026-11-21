@echo off
setlocal
title DSH Lazy Pack Installer
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" goto success
echo [FAILED] Installation stopped with exit code %EXIT_CODE%.
echo Keep the PowerShell error output above for troubleshooting.
goto finish
:success
echo [SUCCESS] Installation completed. Restart DSH completely.
:finish
if defined DSH_INSTALL_NO_PAUSE goto exit
echo Press any key to close this window...
pause >nul
:exit
exit /b %EXIT_CODE%
