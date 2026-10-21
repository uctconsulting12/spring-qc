@echo off
setlocal enabledelayedexpansion
REM ============================================================================
REM  Spring QC Server - build script.
REM
REM  Produces dist\SpringQCServer\ containing SpringQCServer.exe (foreground)
REM  and SpringQCService.exe (Windows Service), with GPU-accelerated PyTorch,
REM  the exact same app.py / detector.py from spring-qc-app, unmodified.
REM
REM  IMPORTANT - disk space: a CUDA-enabled PyTorch build plus PyInstaller's
REM  staging area needs 15-20+ GB free. By default this script builds
REM  entirely on BUILD_DRIVE (below) rather than the drive this repo lives
REM  on, specifically so it never touches a system/OS drive that's low on
REM  space. Point it at whichever drive on your build machine actually has
REM  the room; it does not have to be the same drive as the source checkout.
REM ============================================================================

REM ---- edit these two if needed --------------------------------------------
set BUILD_DRIVE=E:
set BUILD_ROOT=%BUILD_DRIVE%\SpringQC-Build
REM CPU-only fallback: set TORCH_INDEX=https://download.pytorch.org/whl/cpu
set TORCH_INDEX=https://download.pytorch.org/whl/cu124
REM ---------------------------------------------------------------------------

set SCRIPT_DIR=%~dp0
set VENV_DIR=%BUILD_ROOT%\venv
set WORK_DIR=%BUILD_ROOT%\work
set DIST_DIR=%BUILD_ROOT%\dist

REM pip's cache and Windows' TEMP both default to the system drive - for a
REM multi-GB CUDA download that matters even when everything else above is
REM correctly pointed at BUILD_DRIVE. Redirect both explicitly so a tight C:
REM drive is never at risk from running this script.
set PIP_CACHE_DIR=%BUILD_ROOT%\pip-cache
set TEMP=%BUILD_ROOT%\tmp
set TMP=%BUILD_ROOT%\tmp
mkdir "%TEMP%" 2>nul

echo.
echo === Spring QC Server build ===
echo Source (unmodified):  %SCRIPT_DIR%..\spring-qc-app
echo Build workspace:       %BUILD_ROOT%
echo Torch index:           %TORCH_INDEX%
echo.

if not exist "%BUILD_DRIVE%\" (
    echo ERROR: %BUILD_DRIVE% does not exist on this machine. Edit BUILD_DRIVE in this script.
    exit /b 1
)

mkdir "%BUILD_ROOT%" 2>nul

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo Creating build venv at %VENV_DIR% ...
    python -m venv "%VENV_DIR%" || exit /b 1
)
call "%VENV_DIR%\Scripts\activate.bat"

python -m pip install --upgrade pip

echo.
echo --- Installing CUDA PyTorch (this is the multi-GB download) ---
pip install --index-url %TORCH_INDEX% torch torchvision || exit /b 1

echo.
echo --- Installing the app's own requirements (unmodified) ---
pip install -r "%SCRIPT_DIR%..\..\spring-qc-app\requirements.txt" || exit /b 1

echo.
echo --- Installing build tools ---
pip install -r "%SCRIPT_DIR%requirements-build.txt" || exit /b 1

echo.
echo --- Registering the pywin32 service API (one-time per venv) ---
python "%VENV_DIR%\Scripts\pywin32_postinstall.py" -install >nul 2>&1

if not exist "%SCRIPT_DIR%vendor\postgres\bin\pg_ctl.exe" (
    echo.
    echo NOTE: vendor\postgres is not populated - the built exe will require an
    echo external DATABASE_URL ^(set it in springqc.ini^) rather than a bundled
    echo database. To bundle Postgres instead, download the "binaries zip" from
    echo https://www.enterprisedb.com/download-postgresql-binaries and extract
    echo its pgsql\ folder to: %SCRIPT_DIR%vendor\postgres\
)

echo.
echo --- Running PyInstaller ---
pyinstaller "%SCRIPT_DIR%springqc.spec" ^
    --distpath "%DIST_DIR%" ^
    --workpath "%WORK_DIR%" ^
    --noconfirm

if errorlevel 1 (
    echo.
    echo BUILD FAILED - see the PyInstaller output above.
    exit /b 1
)

echo.
echo === Build complete ===
echo Output: %DIST_DIR%\SpringQCServer\
echo   SpringQCServer.exe   - run this directly to try it in the foreground
echo   SpringQCService.exe  - installer\SpringQC-Server.iss wires this up as a service
echo.
echo Next: installer\build_installer.bat (needs Inno Setup) to produce a
echo single SpringQC-Server-Setup.exe from this output.
endlocal
