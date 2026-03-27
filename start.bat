@echo off
setlocal

cd /d "%~dp0"
set "OPENCV_LOG_LEVEL=ERROR"

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "main.py"
    goto :end
)

python "main.py"

:end
endlocal
