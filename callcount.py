# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
The FIS's own online requests per UTC day (A4, 5.1.0): one daily cap for
plugin and FIS together.

The plugin logs every request in its database (external_calls); the FIS
reads that log, but its own requests (Spansh: carriers near me, a carrier's
position) were counted only in its memory - after a FIS restart another 50
were free, and the plugin never saw them. Now the FIS keeps its count in
FIS/fis_calls.json (next to fis.ini, written atomically, only by the FIS):
{"day": <UTC day number>, "counts": {"spansh": n}}. The FIS seeds its
gateway with the plugin's log plus this file; the plugin adds the file when
it seeds its own at start-up.

Standard library only; never raises.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Callable, Dict, Optional

FILE_NAME = "fis_calls.json"
_LOCK = threading.Lock()

__all__ = ["FILE_NAME", "plugin_path", "today", "add"]


def plugin_path(plugin_dir: str) -> str:
    """Where the FIS keeps the file in a plugin folder."""
    return os.path.join(plugin_dir, "FIS", FILE_NAME)


def _day(clock: Callable[[], float]) -> int:
    return int(clock() // 86400)


def today(path: Optional[str], clock: Callable[[], float] = time.time) -> Dict[str, int]:
    """The FIS's requests per service on the current UTC day ({} when none,
    the file is missing or from another day)."""
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if int(data.get("day", -1)) != _day(clock):
            return {}
        return {str(k): int(v) for k, v in (data.get("counts") or {}).items() if int(v) > 0}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def add(path: str, counts: Dict[str, int], clock: Callable[[], float] = time.time) -> Dict[str, int]:
    """Count requests the FIS sent (per service); a new UTC day starts at 0.
    Returns today's counts; a write failure leaves the file as it was."""
    with _LOCK:
        now = today(path, clock)
        for k, n in counts.items():
            if n:
                now[k] = now.get(k, 0) + int(n)
        tmp = "%s.%d.tmp" % (path, os.getpid())
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"day": _day(clock), "counts": now}, fh, sort_keys=True)
            os.replace(tmp, path)
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass
        return now
