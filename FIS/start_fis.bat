@echo off
rem This Source Code Form is subject to the terms of the Mozilla Public
rem License, v. 2.0. If a copy of the MPL was not distributed with this
rem file, You can obtain one at https://mozilla.org/MPL/2.0/.
rem SPDX-License-Identifier: MPL-2.0
rem Copyright (c) 2025-2026 Shodanki
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
