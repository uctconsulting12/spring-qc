@echo off
cd /d "%~dp0"

REM Use the local virtual environment if it exists, otherwise fall back to
REM whatever "python" is on PATH.
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"

echo Starting Spring QC (Admin / Operator)...
echo   Admin:    http://localhost:8001/admin
echo   Operator: http://localhost:8001/operator
echo   Monitor:  http://localhost:8001/monitor
echo   Reports:  http://localhost:8001/reports
echo.
"%PY%" -m uvicorn app:app --host 0.0.0.0 --port 8001
pause
