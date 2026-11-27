@echo off
chcp 65001 >nul
cd /d "%~dp0"
title OilTech Radar 4

if not exist ".venv\Scripts\python.exe" (
  echo Сначала запустите УСТАНОВКА.cmd.
  pause
  exit /b 1
)

set "PYTHONUTF8=1"
set "PYTHONPATH=%~dp0"
echo Откройте в браузере http://127.0.0.1:8085
echo Для остановки нажмите Ctrl+C.
".venv\Scripts\python.exe" -m portal.app
echo.
echo Портал завершил работу. Код выхода: %ERRORLEVEL%
pause
