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
rem Python: the py launcher (python.org installs it) picks the newest 3.x;
rem else a python.org install for this user; else python on the PATH.
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do set "PY=%%D\python.exe"
if not defined PY set "PY=python"
title SHBOX FIS
%PY% -m fis %*
if errorlevel 1 (
  echo.
  echo SHBOX FIS stopped with an error. Needs Python 3.11+ ^(python.org, standard library only^).
  pause
)
endlocal
