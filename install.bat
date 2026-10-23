@echo off
setlocal
cd /d "%~dp0"
title ClipForge setup
echo.
echo  ===== ClipForge setup =====
echo  This installs everything ClipForge needs. It can take 5 to 10 minutes.
echo.

where winget >nul 2>&1
if errorlevel 1 (
  echo  [!] winget is missing. Open the Microsoft Store, install "App Installer", then run this again.
  pause
  exit /b 1
)

set "PY="
call :findpy
if not defined PY (
  echo  Installing Python 3.12...
  winget install -e --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements
  call :findpy
)
if not defined PY (
  echo.
  echo  [!] Python was installed, but Windows needs a fresh window to see it.
  echo      Close this window and double-click install.bat again.
  pause
  exit /b 1
)
echo  Python found.

where ffmpeg >nul 2>&1
if errorlevel 1 if not exist "%LOCALAPPDATA%\Microsoft\WinGet\Links\ffmpeg.exe" (
  echo  Installing FFmpeg, the video engine...
  winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
)

where deno >nul 2>&1
if errorlevel 1 if not exist "%LOCALAPPDATA%\Microsoft\WinGet\Links\deno.exe" (
  echo  Installing Deno, which the YouTube downloader needs...
  winget install -e --id DenoLand.Deno --accept-source-agreements --accept-package-agreements
)

if not exist ".venv\Scripts\python.exe" (
  echo  Creating ClipForge's private Python environment...
  %PY% -m venv .venv
)
echo  Installing Python packages...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo  [!] Package install failed. Check your internet connection and run install.bat again.
  pause
  exit /b 1
)

echo.
echo  ===== Done! =====
echo  Double-click start.bat to open ClipForge.
echo.
pause
exit /b 0

:findpy
py -3.12 -c "import sys" >nul 2>&1 && (set "PY=py -3.12" & exit /b 0)
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (set "PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"" & exit /b 0)
py -3 -c "import sys; exit(0 if (3,10) <= sys.version_info[:2] <= (3,13) else 1)" >nul 2>&1 && (set "PY=py -3" & exit /b 0)
exit /b 0
