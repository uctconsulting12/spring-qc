@echo off
REM Double-click this on any client PC (admin PC, operator panel, etc.) to
REM create Desktop shortcuts that open Spring QC pages in the default
REM browser. Asks for the server's address once; no install, no admin
REM rights needed.

setlocal
echo Spring QC - client shortcut setup
echo.
set /p SERVER_IP="Enter the Spring QC server's IP address (e.g. 192.168.1.50): "

if "%SERVER_IP%"=="" (
    echo No address entered - aborting.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Create-SpringQCShortcuts.ps1" -ServerAddress %SERVER_IP%

echo.
pause
