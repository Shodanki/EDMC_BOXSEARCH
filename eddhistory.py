# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
5.0: older journal lines from EDDiscovery's archive, for the learnt models.

EDDiscovery keeps every journal line it read in ``EDDUser.sqlite`` (table
``JournalEntries``, the line as JSON, per EDDiscovery commander). With the
setting *learn from EDDiscovery's archive* (off by default) the plugin's
fuel model and the tonnes per rock start from those years instead of the
last journals on disk: lines() hands out the lines older than the journals
the plugin replays, in their order, and the models take them like any
journal line.

Least privilege, as in the FIS (FIS/fis/eddarchive.py):
  * the file is opened read only (``mode=ro``) and never written;
  * of ``Commanders`` only ``Id`` is read - the table also holds the EDSM
    API key, which is never read;
  * only the asked event names, plus the login lines that name the commander;
    lines before a commander's first login there are left out.

Run in a worker only (the file is large). Nothing is sent anywhere.
"""

from __future__ import annotations

import calendar
import json
import os
import sqlite3
import time
from typing import Any, Dict, Iterable, Iterator, List, Optional

FILE = "EDDUser.sqlite"
CANDIDATES = (r"%LOCALAPPDATA%\EDDiscovery", r"%APPDATA%\EDDiscovery")
LOGIN = ("LoadGame", "Commander")


def find(edd_system_path: Optional[str] = None) -> Optional[str]:
    """EDDUser.sqlite beside the plugin's EDDSystem.sqlite, else in
    EDDiscovery's default folders; None if there is none."""
    dirs: List[str] = []
    if edd_system_path:
        dirs.append(os.path.dirname(os.path.expandvars(str(edd_system_path))))
    dirs.extend(os.path.expandvars(d) for d in CANDIDATES)
    for d in dirs:
        p = os.path.join(d, FILE)
        if "%" not in p and os.path.isfile(p):
            return p
    return None


def connect(path: str) -> sqlite3.Connection:
    """The file, read only."""
    uri = "file:" + path.replace("\\", "/").replace("?", "%3f").replace("#", "%23") + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=5)


def lines(path: str, names: Iterable[str], before: Optional[float] = None) -> Iterator[Dict[str, Any]]:
    """Every line of the asked events (and the login lines) older than
    ``before`` (Unix time; None: all), commander by commander, each in its
    order. A commander's lines count from its first login line on."""
    wanted = sorted(set(names) | set(LOGIN))
    # a full date string either way: EventTime has numeric affinity, a bare "9999"
    # would be compared as a number and no text row is ever below it
    cut = time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime(before)) if before is not None else "9999-12-31 23:59:59Z"
    con = connect(path)
    try:
        # Id only: the same table holds the EDSM API key
        cids = [cid for (cid,) in con.execute("SELECT Id FROM Commanders ORDER BY Id")]
        q = ("SELECT EventType, EventData FROM JournalEntries WHERE CommanderId = ? AND EventTime < ? "
             "AND EventType IN (%s) ORDER BY Id" % ",".join("?" * len(wanted)))
        for cid in cids:
            seen_login = False
            for kind, data in con.execute(q, [cid, cut] + wanted):
                seen_login = seen_login or kind in LOGIN
                if not seen_login:
                    continue
                try:
                    e = json.loads(data)
                except (TypeError, ValueError):
                    continue
                if isinstance(e, dict) and e.get("timestamp"):
                    yield e
    finally:
        con.close()


def first_time(files: List[str]) -> Optional[float]:
    """Unix time of the first line of the oldest journal file - the archive
    gives what is older (journal_files() lists the oldest first)."""
    for fn in files[:1]:
        try:
            with open(fn, "r", encoding="utf-8", errors="replace") as f:
                ts = json.loads(f.readline()).get("timestamp")
            return float(calendar.timegm(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")))
        except (OSError, ValueError, TypeError, AttributeError):
            return None
    return None
