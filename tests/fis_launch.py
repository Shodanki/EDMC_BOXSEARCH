# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
The plugin starts the FIS minimised without a shell (M11, audit 21.11.).

Up to 5.0.0 the start command was one string with shell=True and the path
of start_fis.bat in it; a plugin folder with & or ^ in its name broke or
extended the command. Now it is an argument list.

    python tests/fis_launch.py      (from the plugin folder)
"""
import os
import subprocess
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plugin_pkg  # noqa: E402
plugin_pkg.import_plugin()                # EDMC stubs, then the package
from SHBOXSEARCH import fislaunch  # noqa: E402

calls = []
odd = os.path.join("C:\\", "Games & Co^", "SHBOXSEARCH", "FIS", "start_fis.bat")
with mock.patch.object(fislaunch, "FIS_BAT", odd), \
        mock.patch.object(fislaunch.os.path, "exists", lambda p: True), \
        mock.patch.object(fislaunch, "_fis_settings", lambda: {"port": "8765"}), \
        mock.patch.object(fislaunch, "_fis_running", lambda port: False), \
        mock.patch.object(fislaunch, "_fis_setup_done", lambda: True), \
        mock.patch.object(subprocess, "Popen", lambda *a, **k: calls.append((a, k))):
    fislaunch._fis_start(minimized=True)
ok = (len(calls) == 1 and isinstance(calls[0][0][0], list) and calls[0][0][0][-1] == odd
      and not calls[0][1].get("shell"))
print("  [%s] the FIS starts minimised from an argument list, no shell (%s)" % ("OK" if ok else "FAIL", calls))
sys.exit(0 if ok else 1)
