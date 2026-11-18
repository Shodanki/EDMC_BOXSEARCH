# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
FX4 (5.0): systems the plugin holds but never looked up are asked in
EDDiscovery's file by id64 - local, read only, no network.

The FX measurement (18.11.2026, developer's database) found 626 systems
from plotted routes (NavRoute) with no database source: 622 from before
the I1 route check existed, 4 checked since. EDDiscovery's file knew 624
of them. Each of them counted as "not checked", so the find odds
(findodds) had no level to learn from and the views could not tell them
from systems really in no database.

Two calls, both from EDMC's main thread, the work on a worker thread:

    backfill()        once per session after the first arrival: every
                      system with an id64, no database source and no valid
                      check, at most BACKFILL_MAX
    check_target(e)   FSDTarget: the selected system, before the jump, so
                      the first arrival's prediction (findlog) knows its
                      level

What EDD has is stored with source EDDiscovery ("known"). What it lacks
and has an exact position is kept as a tiny checked region, like the I1
route check, so the level is "checked" - in no database. The check never
reaches Tk.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import shells
from .state import CFG, ST, cfg_bool, logger
from .sysdb import Q_ESTIMATE

BACKFILL_MAX = 5000      # systems asked in one backfill (one indexed query per 500)
CHECK_R = 0.1            # ly: the region a check leaves - one system (as I1)
CHUNK = 100              # systems stored per hold of ST.lock
_EXTERNAL = ("EDDiscovery", "Spansh", "EDSM")

Row = Tuple[str, int, Optional[Tuple[float, float, float]]]


def _edd():
    """EDDiscovery's source when it may be asked now, else None."""
    if ST.sources is None or not cfg_bool(CFG["src_edd"], True):
        return None
    edd = ST.sources.sources.get("edd")
    look = getattr(edd, "lookup_id64", None)
    if look is None:
        return None
    try:
        return edd if edd.available()[0] else None
    except Exception:
        return None


def unlooked(db: Any, limit: int = BACKFILL_MAX, lock: Any = None) -> List[Row]:
    """(name, id64, position for a new check or None) of the systems with an
    id64 and no database source: not checked, or checked as "in no
    database" - EDD's file may have them since (it is updated; 18.11.: one
    of three such systems). An exact position is handed only to a system
    not checked yet, so a check is never kept twice - and never to a row
    of the old imports with the source "external" (a database had it, only
    which one is lost; boxelplan and sysdb count it as one). With ``lock`` it is
    held only while the database is read, not while sorting out."""
    with lock if lock is not None else _NoLock():
        regions = {k: db.valid_shells(k) for k in ("edd", "spansh", "edsm")}
        rows = db.cx.execute("SELECT name, id64, x, y, z, quality, sources FROM systems "
                             "WHERE id64 IS NOT NULL").fetchall()
    out: List[Row] = []
    for r in rows:
        srcs = set((r["sources"] or "").split(","))
        if srcs & set(_EXTERNAL):
            continue
        pos = None
        if r["x"] is not None and (r["quality"] or 0) > Q_ESTIMATE:
            pos = (float(r["x"]), float(r["y"]), float(r["z"]))
        lv = shells.info_level(srcs, pos, regions)[0]
        if lv not in ("unchecked", "checked"):
            continue
        fresh = lv == "unchecked" and "external" not in srcs
        out.append((r["name"], int(r["id64"]), pos if fresh else None))
        if len(out) >= limit:
            break
    return out


class _NoLock:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc: Any) -> None:
        return None


def settle(rows: Sequence[Row], found: Sequence[Dict[str, Any]], source: str,
           ttl: float) -> Tuple[int, int]:
    """Store what EDD found (source ``source``) and keep a checked region
    for each system it lacks that has an exact position. Takes ST.lock for
    CHUNK systems at a time, so EDMC's main thread never waits long.
    Returns (known, checked)."""
    have = {int(f["id64"]): f for f in found if f.get("id64")}
    known = checked = 0
    for i in range(0, len(rows), CHUNK):
        with ST.lock:
            for name, id64, pos in rows[i:i + CHUNK]:
                f = have.get(id64)
                if f is not None:
                    ST.db.upsert(f.get("name") or name, f.get("x"), f.get("y"), f.get("z"),
                                 id64=id64, source=source, commit=False)
                    known += 1
                elif pos is not None:
                    ST.db.record_shell("edd", pos, 0.0, CHECK_R, 0, ttl)
                    checked += 1
            ST.db.cx.commit()
    return known, checked


def _ask(rows: Sequence[Row], what: str) -> Optional[Tuple[int, int]]:
    """Look rows up in EDD and settle them; None when EDD cannot be asked."""
    edd = _edd()
    if edd is None or not rows:
        return None
    found = edd.lookup_id64([i for _n, i, _p in rows])
    if found is None:
        return None                        # busy or another layout: asked again later
    known, checked = settle(rows, found, edd.name, shells.ttl_seconds())
    logger.info("EDD check | %s: %d systems never looked up - %d in EDDiscovery's file, "
                "%d in no local database (checked), %d without an exact position",
                what, len(rows), known, checked, len(rows) - known - checked)
    return known, checked


def run_backfill() -> Optional[Tuple[int, int]]:
    """The backfill itself (worker thread). Never raises."""
    try:
        if ST.sources is not None and ST.cur_id64 and ST.cur_pos:
            ST.sources.set_reference(ST.cur_id64, ST.cur_pos)
        return _ask(unlooked(ST.db, lock=ST.lock), "backfill")
    except Exception:
        logger.exception("EDD check failed")
        return None


def backfill() -> None:
    """Once per session, after the first arrival (EDD calibrates against it):
    start the backfill on a worker thread."""
    if ST.db is None or getattr(ST, "edd_backfilled", False):
        return
    ST.edd_backfilled = True
    threading.Thread(target=run_backfill, daemon=True, name="SHBOX-eddcheck").start()


def run_target(name: str, id64: int) -> Optional[Tuple[int, int]]:
    """Check one selected system (worker thread). Never raises."""
    try:
        with ST.lock:
            row = ST.db.system_by_id64(id64)
            srcs = set(((row["sources"] if row is not None else "") or "").split(","))
            pos = None
            if row is not None and row["x"] is not None and (row["quality"] or 0) > Q_ESTIMATE:
                pos = (float(row["x"]), float(row["y"]), float(row["z"]))
            regions = {k: ST.db.valid_shells(k) for k in ("edd", "spansh", "edsm")}
            if shells.info_level(srcs, pos, regions)[0] != "unchecked":
                return None
        return _ask([(name, int(id64), pos)], "target %s" % name)
    except Exception:
        logger.exception("EDD check failed")
        return None


def check_target(entry: Dict[str, Any]) -> None:
    """FSDTarget: look the selected system up before the jump."""
    name, id64 = entry.get("Name"), entry.get("SystemAddress")
    if ST.db is None or not name or not id64:
        return
    threading.Thread(target=run_target, args=(name, int(id64)), daemon=True,
                     name="SHBOX-eddcheck").start()
