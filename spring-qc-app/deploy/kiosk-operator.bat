@echo off
REM Launches the Operator screen full-screen, kiosk-mode, on a Windows touch
REM panel. Put a shortcut to this file in the shell:startup folder (Win+R,
REM type shell:startup, drop a shortcut in) so it comes up automatically
REM after every reboot / power cycle - no keyboard needed on the panel.
REM
REM Edit EDGE_HOST below to the edge box's IP or hostname first.

setlocal
set EDGE_HOST=192.168.1.50
set EDGE_PORT=8001
set URL=http://%EDGE_HOST%:%EDGE_PORT%/operator

REM Prefer Chrome; fall back to Edge if Chrome isn't installed.
set CHROME="%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist %CHROME% set CHROME="%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist %CHROME% set CHROME="%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"

start "" %CHROME% ^
    --kiosk "%URL%" ^
    --noerrdialogs ^
    --disable-session-crashed-bubble ^
    --disable-infobars ^
    --disable-pinch ^
    --overscroll-history-navigation=0 ^
    --autoplay-policy=no-user-gesture-required ^
    --user-data-dir="%LOCALAPPDATA%\SpringQCKiosk"
