@echo off
setlocal
REM Spring QC HMI - build script. Lightweight (no GPU/ML deps), builds fine
REM on the same drive as the source, but still targets BUILD_DRIVE by
REM default to keep every build artifact off a possibly-tight system drive.

set BUILD_DRIVE=E:
set BUILD_ROOT=%BUILD_DRIVE%\SpringQC-Build-HMI
set SCRIPT_DIR=%~dp0
set VENV_DIR=%BUILD_ROOT%\venv

REM Keep pip's cache and TEMP off the system drive too, even though this
REM build is small - see server\build.bat for why this matters.
set PIP_CACHE_DIR=%BUILD_ROOT%\pip-cache
set TEMP=%BUILD_ROOT%\tmp
set TMP=%BUILD_ROOT%\tmp
mkdir "%TEMP%" 2>nul

if not exist "%BUILD_DRIVE%\" (
    echo ERROR: %BUILD_DRIVE% does not exist on this machine. Edit BUILD_DRIVE in this script.
    exit /b 1
)

mkdir "%BUILD_ROOT%" 2>nul

if not exist "%VENV_DIR%\Scripts\python.exe" (
    python -m venv "%VENV_DIR%" || exit /b 1
)
call "%VENV_DIR%\Scripts\activate.bat"

python -m pip install --upgrade pip
pip install -r "%SCRIPT_DIR%requirements.txt" || exit /b 1
python "%VENV_DIR%\Scripts\pywin32_postinstall.py" -install >nul 2>&1

pyinstaller "%SCRIPT_DIR%springqc_hmi.spec" ^
    --distpath "%BUILD_ROOT%\dist" ^
    --workpath "%BUILD_ROOT%\work" ^
    --noconfirm

if errorlevel 1 (
    echo BUILD FAILED
    exit /b 1
)

echo.
echo === Build complete ===
echo Output: %BUILD_ROOT%\dist\SpringQCHMI\SpringQCHMI.exe
endlocal
