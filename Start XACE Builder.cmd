@echo off
setlocal
cd /d "%~dp0"

python tools\xace_builder_launch.py %*
if errorlevel 1 (
  echo.
  echo XACE Builder could not start. Read the message above, then press any key to close this window.
  pause >nul
)
