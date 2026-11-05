@echo off
rem SHBOX FIS - double-click to start. The very first start asks a few
rem questions (language, this PC only or home network, browser) and keeps
rem the answers in fis.ini. Change them later with fis_settings.bat.
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set "PY=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
if not exist "%PY%" (
  where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
)
title SHBOX FIS
%PY% -m fis %*
if errorlevel 1 (
  echo.
  echo SHBOX FIS stopped with an error. Needs Python 3.10+ ^(standard library only^).
  pause
)
endlocal
