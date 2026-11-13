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
rem Python: the py launcher (python.org installs it) picks the newest 3.x;
rem else a python.org install for this user; else python on the PATH.
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do set "PY=%%D\python.exe"
if not defined PY set "PY=python"
title SHBOX FIS - settings
%PY% -m fis --setup
if errorlevel 1 pause
endlocal
