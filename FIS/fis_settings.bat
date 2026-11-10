@echo off
rem This Source Code Form is subject to the terms of the Mozilla Public
rem License, v. 2.0. If a copy of the MPL was not distributed with this
rem file, You can obtain one at https://mozilla.org/MPL/2.0/.
rem SPDX-License-Identifier: MPL-2.0
rem Copyright (c) 2025-2026 Shodanki
rem SHBOX FIS - change the settings of the first start (language, network,
rem browser, port, firewall rule for the home network). Then start the FIS.
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set "PY=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
if not exist "%PY%" (
  where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
)
title SHBOX FIS - settings
%PY% -m fis --setup
if errorlevel 1 pause
endlocal
