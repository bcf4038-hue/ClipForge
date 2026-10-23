@echo off
cd /d "%~dp0"
title ClipForge
if not exist ".venv\Scripts\python.exe" (
  echo  ClipForge is not installed yet. Double-click install.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" update.py
".venv\Scripts\python.exe" app.py
pause
