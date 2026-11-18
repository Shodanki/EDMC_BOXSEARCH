# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
FX3 (5.0) V0 loop, the plugin's side: on an FSDJump the chance of a find
(findodds) is worked out for the new system from what was known before the
visit, and kept in find_log for the commander's first visit. Runs on a
worker thread; touches no Tk.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional

from . import findodds
from . import shells
from .procgen import star_pos
from .state import ST, logger


def on_jump(entry: Dict[str, Any]) -> None:
    """FSDJump: on a first visit (no own scans in the system yet) hand the
    prediction to a worker thread; one indexed look-up here, nothing slow."""
    sid = entry.get("SystemAddress")
    if not ST.db or not sid:
        return
    # decided now, before the arrival star's scan is stored: a first visit?
    with ST.lock:
        if ST.db.has_own_scans(ST.db.fid, sid):
            return
    threading.Thread(target=keep_prediction, args=(dict(entry),), daemon=True,
                     name="SHBOX-findodds").start()


def level_before(name: str, pos: Optional[Any]) -> str:
    """shells.info_level of a system from the database as it stands (the
    journal adds no database source, so this is the state before the visit)."""
    row = ST.db.system(name)
    srcs = set((row["sources"] or "").split(",")) if row is not None else set()
    regions = {k: ST.db.valid_shells(k) for k in ("edd", "spansh", "edsm")}
    return shells.info_level(srcs, pos, regions)[0]


def keep_prediction(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Work out and keep the prediction of one first arrival; returns it
    (None when nothing was kept). Never raises."""
    try:
        name, sid = entry.get("StarSystem") or "", entry.get("SystemAddress")
        with ST.lock:
            fid = ST.db.fid
            pos = star_pos(entry.get("StarPos"))
            level = level_before(name, pos)
            pred = findodds.model(lambda q, a: ST.db.cx.execute(q, a).fetchall(),
                                  skip=(fid, sid)).predict(name, entry.get("StarClass"), level,
                                                           pos[1] if pos else None)
            kept = ST.db.keep_find_prediction(fid, sid, entry.get("timestamp") or "", name, pred)
        if kept:
            logger.info("find odds | %s: %.0f %% (%.0f-%.0f %%, %s, from %d visits)", name, 100 * pred["p"],
                        100 * pred["low"], 100 * pred["high"], pred["why"], pred["learnt"])
            return pred
    except Exception:
        logger.exception("find odds failed")
    return None


HINT_RATIO = 1.5          # the other height band must pay this much better to say so


def height_hint(y: Optional[float]) -> Optional[Dict[str, Any]]:
    """
    FX4: on starting a sphere near the galactic plane - do the commander's
    own settled visits pay clearly better above or below it (|y| >=
    findodds.HEIGHT_LY)? FX3 measurement: 3 % near the plane, 14 % above or
    below. Only when both bands have findodds.WEIGHT visits and the other
    band pays HINT_RATIO times as often. Returns {here, there, n_here,
    n_there} or None. Worker thread; takes ST.lock.
    """
    if findodds.height_band(y) != "low" or not ST.db:
        return None
    with ST.lock:
        m = findodds.model(lambda q, a: ST.db.cx.execute(q, a).fetchall())
    lo, hi = m.cells.get(("pg", "low"), (0, 0)), m.cells.get(("pg", "high"), (0, 0))
    if lo[1] < findodds.WEIGHT or hi[1] < findodds.WEIGHT:
        return None
    here, there = lo[0] / lo[1], hi[0] / hi[1]
    if there < HINT_RATIO * max(here, 1e-9) or there <= 0:
        return None
    return {"here": here, "there": there, "n_here": lo[1], "n_there": hi[1]}


def height_hint_text(h: Dict[str, Any]) -> str:
    """The panel's status line for a height hint."""
    return ("finds near the plane %.0f %% (%d visits), %.0f ly above/below %.0f %% (%d) - "
            "a sphere there pays more" % (100 * h["here"], h["n_here"], findodds.HEIGHT_LY,
                                          100 * h["there"], h["n_there"]))
