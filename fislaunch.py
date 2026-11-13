# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""Starting and opening SHBOX FIS.

The FIS runs as its own Python process from the FIS folder (EDMC's
built-in Python cannot host it). This module reads its settings from
``FIS/fis.ini``, finds a Python, starts it and opens the browser. The
FIS starts with EDMC only when the user ticked that.
"""

from __future__ import annotations

import os
import threading
from typing import Dict, Optional

from .state import CFG, _PLUGIN_DIR, cfg_bool, logger

FIS_DIR = os.path.join(_PLUGIN_DIR, "FIS")
FIS_BAT = os.path.join(FIS_DIR, "start_fis.bat")


def _fis_settings() -> Dict[str, str]:
    """Port, LAN and token from FIS/fis.ini (written by the FIS's first start)."""
    import configparser
    cp = configparser.ConfigParser(interpolation=None)
    try:
        cp.read(os.path.join(FIS_DIR, "fis.ini"), encoding="utf-8")
    except Exception:
        pass
    s = cp["fis"] if cp.has_section("fis") else {}
    return {"port": str(s.get("port", "8770") or "8770"), "lan": str(s.get("lan", "false")),
            "token": str(s.get("token", "") or "")}


def _fis_python() -> Optional[str]:
    """A Python the start script will find (same order as start_fis.bat)."""
    import glob
    import shutil
    local = os.environ.get("LOCALAPPDATA", "")
    found = sorted(glob.glob(os.path.join(local, "Programs", "Python", "Python3*", "python.exe")),
                   reverse=True)
    return found[0] if found else (shutil.which("py") or shutil.which("python"))


def _fis_running(port: str) -> bool:
    import socket
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=0.3):
            return True
    except (OSError, ValueError):
        return False


def _fis_status() -> str:
    if not os.path.exists(FIS_BAT):
        return "FIS folder not found (download the full release)"
    st = _fis_settings()
    if _fis_running(st["port"]):
        return "running on port %s%s" % (st["port"], " (home network)" if st["lan"].lower() == "true" else "")
    py = _fis_python()
    return ("not running - Python found: %s" % py) if py else \
        "not running - needs Python 3.11+ (python.org), EDMC's Python cannot run it"


def _fis_setup_done() -> bool:
    import configparser
    cp = configparser.ConfigParser(interpolation=None)
    try:
        cp.read(os.path.join(FIS_DIR, "fis.ini"), encoding="utf-8")
        return cp.get("fis", "setup_done", fallback="false").strip().lower() == "true"
    except Exception:
        return False


def _fis_start(minimized: bool = False, open_if_running: bool = True) -> None:
    """
    Start the FIS in its own console window - independent of EDMC, it keeps
    running when EDMC closes. Minimised only once the first-start questions
    have been answered (they need the window).
    """
    if not os.path.exists(FIS_BAT):
        return
    st = _fis_settings()
    if _fis_running(st["port"]):
        if open_if_running:
            _fis_open()
        return
    try:
        if minimized and _fis_setup_done():
            import subprocess
            subprocess.Popen('start "SHBOX FIS" /min "%s"' % FIS_BAT, shell=True, cwd=FIS_DIR)
        else:
            os.startfile(FIS_BAT)
        logger.info("FIS | started %s%s", FIS_BAT, " (minimised)" if minimized else "")
    except Exception:
        logger.exception("FIS | could not start %s", FIS_BAT)


FIS_AUTOSTART_DELAY_MS = 4000      # let EDMC finish starting first


def _fis_autostart() -> None:
    """Start the FIS with EDMC when the commander asked for it (settings)."""
    if not cfg_bool(CFG["fis_autostart"], False) or not os.path.exists(FIS_BAT):
        return
    threading.Thread(target=lambda: _fis_start(minimized=True, open_if_running=False),
                     name="shbox-fis-autostart", daemon=True).start()


def _fis_open() -> None:
    """Open the running FIS in the browser of this PC."""
    import webbrowser
    st = _fis_settings()
    url = "http://127.0.0.1:%s/" % st["port"]
    if st["lan"].lower() == "true" and st["token"]:
        url += "?token=" + st["token"]
    try:
        webbrowser.open(url)
    except Exception:
        logger.exception("FIS | could not open the browser")
