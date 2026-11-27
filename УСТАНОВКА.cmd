@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Установка OilTech Radar 4

py -3.11 --version >nul 2>&1
if errorlevel 1 (
  echo Требуется Python 3.11 с сайта python.org и доступом через команду py -3.11.
  echo После установки Python запустите этот файл ещё раз.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  py -3.11 -m venv .venv
  if errorlevel 1 goto :failed
)

".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :failed

if not exist ".env" copy ".env.example" ".env" >nul
echo.
echo Установка завершена. Для просмотра сохранённых данных ключ API не нужен.
echo Для добавления источников и обновления данных заполните API_KEY в .env.
echo Затем запустите СТАРТ.cmd.
pause
exit /b 0

:failed
echo Установка не завершилась. Проверьте сообщение об ошибке выше.
pause
exit /b 1
