@echo off
REM Double-click this file to download every resume.
cd /d "%~dp0"
where python >nul 2>nul && (python get_resumes.py) || (
  where py >nul 2>nul && (py get_resumes.py) || (
    echo Python is not installed.
    echo Install it from https://www.python.org/downloads/ then double-click this again.
  )
)
echo.
pause
