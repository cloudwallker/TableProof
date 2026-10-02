@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Python environment not found. Follow the installation steps in README.md.
  pause
  exit /b 1
)
set "PYTHONPATH=%~dp0src"
".venv\Scripts\python.exe" -m tableproof serve --open
pause
