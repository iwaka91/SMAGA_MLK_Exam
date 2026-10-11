@echo off
setlocal
cd /d "%~dp0"
title SMAGA Maliku Exam V1.0 RC1 - Lokal
cls
echo ===============================================
echo   SMAGA MALIKU EXAM V1.0 RC1 (LOCAL)
echo ===============================================
echo Mode demo lokal. Port 8788. PIN Admin 2026.
echo.
set SMAGA_ENV=development
set SMAGA_PORT=8788
set SMAGA_DEMO_MODE=1
where py >nul 2>nul
if %errorlevel%==0 (
  py server.py
  goto done
)
where python >nul 2>nul
if %errorlevel%==0 (
  python server.py
  goto done
)
echo [FAIL] Python 3 tidak ditemukan.
:done
pause
