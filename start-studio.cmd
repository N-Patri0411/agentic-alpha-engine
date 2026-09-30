@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-studio.ps1" %*
if errorlevel 1 (
  echo Alpha Studio could not be started. See the message above.
  exit /b 1
)
