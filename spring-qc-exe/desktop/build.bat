@echo off
setlocal enabledelayedexpansion
REM ============================================================================
REM  Spring QC Desktop - build script.
REM
REM  Produces dist\SpringQCDesktop\SpringQCDesktop.exe - the same server as
REM  SpringQCServer.exe, in a proper window instead of a console, with a
REM  system tray icon. Reuses ..\server\springqc_launcher.py unmodified.
REM
REM  By default this reuses the SAME venv as ..\server\build.bat
REM  (E:\SpringQC-Build\venv) if it already exists, since it already has
REM  GPU PyTorch + every app dependency installed - this build then only
REM  needs to add pystray, which is fast. If that venv does not exist yet,
REM  this script creates its own from scratch (same as the server build).
REM ============================================================================

REM ---- edit these if needed --------------------------------------------------
set BUILD_DRIVE=E:
set SHARED_VENV=%BUILD_DRIVE%\SpringQC-Build\venv
set BUILD_ROOT=%BUILD_DRIVE%\SpringQC-Build-Desktop
set TORCH_INDEX=https://download.pytorch.org/whl/cu124
REM ---------------------------------------------------------------------------

set SCRIPT_DIR=%~dp0
set WORK_DIR=%BUILD_ROOT%\work
set DIST_DIR=%BUILD_ROOT%\dist

if not exist "%BUILD_DRIVE%\" (
    echo ERROR: %BUILD_DRIVE% does not exist on this machine. Edit BUILD_DRIVE in this script.
    exit /b 1
)

mkdir "%BUILD_ROOT%" 2>nul

if exist "%SHARED_VENV%\Scripts\python.exe" (
    echo Reusing existing build venv at %SHARED_VENV% - already has GPU PyTorch + app deps.
    set VENV_DIR=%SHARED_VENV%
) else (
    echo No existing server venv found at %SHARED_VENV% - creating a fresh one for Desktop.
    set VENV_DIR=%BUILD_ROOT%\venv
    if not exist "!VENV_DIR!\Scripts\python.exe" (
        python -m venv "!VENV_DIR!" || exit /b 1
    )
)

REM pip's cache and Windows' TEMP both default to the system drive - redirect
REM both so a tight C: drive is never at risk, same as the server build.
set PIP_CACHE_DIR=%BUILD_ROOT%\pip-cache
set TEMP=%BUILD_ROOT%\tmp
set TMP=%BUILD_ROOT%\tmp
mkdir "%TEMP%" 2>nul

call "%VENV_DIR%\Scripts\activate.bat"

echo.
echo === Spring QC Desktop build ===
echo Venv:             %VENV_DIR%
echo Build workspace:  %BUILD_ROOT%
echo.

if not exist "%VENV_DIR%\Lib\site-packages\torch" (
    echo.
    echo --- Installing CUDA PyTorch (this is the multi-GB download) ---
    pip install --index-url %TORCH_INDEX% torch torchvision || exit /b 1

    echo.
    echo --- Installing the app's own requirements (unmodified) ---
    pip install -r "%SCRIPT_DIR%..\..\spring-qc-app\requirements.txt" || exit /b 1
)

echo.
echo --- Installing Desktop's own requirements (tray icon support etc.) ---
pip install -r "%SCRIPT_DIR%requirements.txt" || exit /b 1

if not exist "%SCRIPT_DIR%..\server\vendor\postgres\bin\pg_ctl.exe" (
    echo.
    echo NOTE: ..\server\vendor\postgres is not populated - the built exe will
    echo require an external DATABASE_URL ^(set it in springqc.ini^) rather than
    echo a bundled database. See ..\server\build.bat for how to populate it.
)

echo.
echo --- Running PyInstaller ---
pyinstaller "%SCRIPT_DIR%springqc_desktop.spec" ^
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
echo Output: %DIST_DIR%\SpringQCDesktop\SpringQCDesktop.exe
echo Double-click it to run - a window opens instead of a console, and
echo minimizes to the system tray instead of closing when you click X.
endlocal
