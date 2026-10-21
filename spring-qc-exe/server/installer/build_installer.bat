@echo off
REM Builds SpringQC-Server-Setup.exe from the output of ..\build.bat.
REM Requires Inno Setup 6 (https://jrsoftware.org/isdl.php) installed.

set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"

if not exist %ISCC% (
    echo Inno Setup 6 not found. Install it from https://jrsoftware.org/isdl.php
    exit /b 1
)

%ISCC% "%~dp0SpringQC-Server.iss"
