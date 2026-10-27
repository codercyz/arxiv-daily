@echo off
rem ArXiv Daily launcher (ASCII only: cmd parses .bat in ANSI codepage)
cd /d "%~dp0"
echo Starting ArXiv Daily ...
".venv\Scripts\python.exe" main.py
if errorlevel 1 (
  echo.
  echo Startup failed. See the message above.
  pause
)
