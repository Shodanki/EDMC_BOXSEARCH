# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
5.0: the EDDiscovery archive - your own older journals, kept by EDDiscovery.

The game deletes nothing, but journals get lost: a new PC, a cleaned folder,
a rewritten journal. EDDiscovery keeps every journal line it ever read in
its user database (``EDDUser.sqlite``, table ``JournalEntries``: the line as
JSON, per EDDiscovery commander). Read here, the FIS learns from years of
play instead of the journals still on disk.

Only while the commander switches it on (settings, off by default). Least
privilege:
  * the file is opened read only (``mode=ro``) and never written;
  * of ``Commanders`` only ``Id`` and ``Name`` are read - the table also holds
    the commander's EDSM API key, which is never read;
  * of ``JournalEntries`` only the commander, the time and the line, and only
    the events the FIS archive keeps (fleet.EVENTS) less the live-only ones
    (EDD_SKIP) - nothing is copied or stored, the events live in memory;
  * every event carries the FID its own login line names; a commander
    EDDiscovery never saw log in is left out (statistics count only the
    active commander, so nothing may be counted for everyone).

h-tab (user 19.11.2026): the galactic mean of a commodity (MeanPrice) is
only in a station's market - a fleet carrier's has 0. EDDiscovery stores
each Market event with the market's items, so market_means() takes the
newest mean per commodity from there (the same switch; only the event
Market, only Name and MeanPrice of its items are kept).

EDDiscovery is Apache-2.0 software; no part of it is used here, only its
file is read. Nothing is sent anywhere.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

FILE = "EDDUser.sqlite"
# where EDDiscovery keeps it by default (the folder of EDDSystem.sqlite)
CANDIDATES = (r"%LOCALAPPDATA%\EDDiscovery", r"%APPDATA%\EDDiscovery")

# Kept by the archive for the live views only, of no use years later - and
# the bulk of EDDiscovery's rows (every signal of every system: 83 000 of
# 142 000 old events in the developer's archive; Cargo another 21 000).
EDD_SKIP = frozenset((
    "FSSSignalDiscovered", "Cargo", "CargoTransfer", "Materials", "MaterialCollected",
    "MaterialDiscarded", "Market", "DockingGranted", "DockingDenied", "ShipTargeted",
    "ShieldState", "HeatWarning", "HeatDamage", "HullDamage", "JetConeDamage", "JetConeBoost",
    "NavBeaconScan", "UnderAttack"))


def find(plugin_edd_path: Optional[str] = None) -> Optional[str]:
    """The path of EDDUser.sqlite: beside the EDDSystem.sqlite the plugin is
    set to, else EDDiscovery's default folders. None if there is none."""
    dirs: List[str] = []
    if plugin_edd_path:
        dirs.append(os.path.dirname(os.path.expandvars(str(plugin_edd_path))))
    dirs.extend(os.path.expandvars(d) for d in CANDIDATES)
    for d in dirs:
        p = os.path.join(d, FILE)
        if "%" not in p and os.path.isfile(p):
            return p
    return None


def signature(path: str) -> Optional[Tuple[int, int]]:
    """(mtime, size) of the file - a new read only when it changed."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return int(st.st_mtime), st.st_size


def _connect(path: str) -> sqlite3.Connection:
    uri = "file:" + path.replace("\\", "/").replace("?", "%3f").replace("#", "%23") + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=5)


def wanted(events: Iterable[str]) -> List[str]:
    """The event names asked from EDDiscovery: the archive's own, the login
    lines (they name the commander), less the live-only ones."""
    return sorted((set(events) | {"Commander", "LoadGame"}) - EDD_SKIP)


def read(path: str, events: Iterable[str],
         take: Callable[[Dict[str, Any], Optional[str], List[Dict[str, Any]]], Optional[str]]
         ) -> Dict[str, Any]:
    """Every wanted event of every EDDiscovery commander, in their order.

    ``take(event, fid, out)`` is the archive's own handling of one journal
    line (fleet.Archive._take): it slims the event, appends it tagged with the
    FID and returns the FID logged in from then on.

    Returns {"events": [...], "commanders": {name: fid}, "rows": n}."""
    names = wanted(events)
    con = _connect(path)
    try:
        # Id and Name only: the same table holds the EDSM API key
        cmdrs = {cid: name for cid, name in con.execute("SELECT Id, Name FROM Commanders")}
        fid_of = _first_fids(con, cmdrs)
        where = "+CommanderId = ? AND +EventType IN (%s)" % ",".join("?" * len(names))
        out: List[Dict[str, Any]] = []
        rows = 0
        for cid, fid in sorted(fid_of.items()):        # never logged in: whose would it be?
            for (data,) in by_id(con, "EventData", where, [cid] + names):
                fid, ok = _take_line(data, fid, take, out)
                rows += ok
    finally:
        con.close()
    return {"events": out, "rows": rows,
            "commanders": {cmdrs[c]: f for c, f in fid_of.items() if c in cmdrs}}


def _take_line(data: Any, fid: str, take: Callable[[Dict[str, Any], Optional[str], List[Dict[str, Any]]],
                                                   Optional[str]], out: List[Dict[str, Any]]) -> Tuple[str, int]:
    """One archive line through ``take``: (the FID from then on, 1 if it was
    a journal line)."""
    try:
        e = json.loads(data)
    except (TypeError, ValueError):
        return fid, 0
    if not isinstance(e, dict) or not e.get("timestamp"):
        return fid, 0
    return take(e, fid, out) or fid, 1


# 0g (5.0.1): EDDiscovery's files run without WAL, so a reader blocks its
# writes for as long as one statement is open - up to 5.0.0 the whole archive
# was one statement (1.2 s warm, several seconds cold), and EDDiscovery died
# on "database is locked" (22.11.2026). Now WINDOW ids per statement (under
# 10 ms on the developer's 322 000 rows), each finished before a line is
# parsed, with PAUSE_S between them for EDDiscovery's writes.
WINDOW = 4000
PAUSE_S = 0.005


def by_id(con: sqlite3.Connection, cols: str, where: str, params: List[Any]) -> Iterable[Tuple[Any, ...]]:
    """Rows of JournalEntries in Id order, WINDOW ids per statement. The
    terms in ``where`` must carry "+" (no index), so each statement is a
    short range of the primary key."""
    top = con.execute("SELECT max(Id) FROM JournalEntries").fetchone()[0] or 0
    q = "SELECT %s FROM JournalEntries WHERE Id > ? AND Id <= ? AND %s ORDER BY Id" % (cols, where)
    lo = 0
    while lo < top:
        rows = con.execute(q, [lo, lo + WINDOW] + list(params)).fetchall()
        lo += WINDOW
        yield from rows
        time.sleep(PAUSE_S)


def market_means(path: str) -> Dict[str, Dict[str, Any]]:
    """h-tab: the newest galactic mean per commodity (raw Name, lower case)
    from the Market events EDDiscovery kept: {name: {"mean", "station", "ts"}}."""
    out: Dict[str, Dict[str, Any]] = {}
    con = _connect(path)
    try:
        for (data,) in by_id(con, "EventData", "+EventType = 'Market'", []):
            try:
                e = json.loads(data)
            except (TypeError, ValueError):
                continue
            if not isinstance(e, dict):
                continue
            ts = e.get("timestamp") or ""
            for it in e.get("Items") or []:
                mean = it.get("MeanPrice") if isinstance(it, dict) else None
                if isinstance(mean, (int, float)) and mean > 0 and it.get("Name"):
                    k = str(it["Name"]).lower()
                    if ts >= (out.get(k) or {}).get("iso", ""):
                        out[k] = {"mean": int(mean), "station": e.get("StationName"), "iso": ts}
    finally:
        con.close()
    return out


def _first_fids(con: sqlite3.Connection, cmdrs: Dict[int, str]) -> Dict[int, str]:
    """EDDiscovery commander -> the first FID its login lines name (for the
    lines before its first login in the archive)."""
    out: Dict[int, str] = {}
    for cid in cmdrs:
        # LIMIT and fetchall: the statement ends before anything else happens
        for (data,) in con.execute("SELECT EventData FROM JournalEntries WHERE CommanderId = ? "
                                   "AND EventType IN ('LoadGame', 'Commander') ORDER BY Id LIMIT 50",
                                   (cid,)).fetchall():
            try:
                fid = json.loads(data).get("FID")
            except (TypeError, ValueError, AttributeError):
                continue
            if fid:
                out[cid] = fid
                break
    return out


def missing_from(local: Iterable[Dict[str, Any]], archive: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The archive's events the journals on disk do not have (same time and
    event name): what EDDiscovery adds. Login markers of the journals on
    disk always win."""
    have = {(e.get("timestamp"), e.get("event")) for e in local}
    return [e for e in archive if (e.get("timestamp"), e.get("event")) not in have]
