@echo off
cd /d "%~dp0host"
if not exist "..\.venv\Scripts\python.exe" (
  echo First create .venv and install host\requirements-gui.txt. See README.md.
  pause
  exit /b 1
)
"..\.venv\Scripts\python.exe" -m motortester.v2 %*
if errorlevel 1 pause
