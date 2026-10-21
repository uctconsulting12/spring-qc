@echo off
cd /d "%~dp0"

echo Creating virtual environment (.venv) ...
python -m venv .venv
if errorlevel 1 (
    echo.
    echo Could not create the virtual environment. Make sure Python 3.10+ is installed and on PATH.
    pause
    exit /b 1
)

echo Installing dependencies ...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt

echo.
echo Done. For GPU inference, install a CUDA build of torch instead, e.g.:
echo   .venv\Scripts\python.exe -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
echo.
echo Now run:  run.bat
pause
