# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
learnreset.py - when a learnt model was reset (SK3, 5.0)
========================================================
The plugin and the FIS learn three models from the commander's journals:

    route   supercruise minutes per leg (sysroute.CostModel: entry, k)
    work    the time a detailed surface scan and a bio sample take
    fuel    fuel per jump, per ship (deepspace.FuelState)
    value   the calibration of exploration values on your own sales (B6,
            FIS UNSOLD DATA)

Both read the journals again at every start, so forgetting a model means
remembering WHEN it was reset: measurements before that moment are left
out from then on. The marks live in FIS/learn_reset.json, next to fis.ini
(like favourites.json, personal, never in the repository, written only
when the commander presses "reset" in the FIS); the plugin reads the same
file at start-up. A missing or broken file means: nothing was reset.

    {"version": 1, "route": 1794909600.0, "work": null,
     "fuel": {"[\\"Cmdr\\", 9, 37]": 1794909600.0},
     "sold": {"F123": {"explo": 1794909600.0, "bio": 1794909600.0}}}

SM1 (5.0): "sold" is no model but a mark of the same kind - per commander
(FID), when they said "my data is sold" because the game logged no sale
(19.11.2026: a Universal Cartographics sale at the own carrier wrote no
MultiSellExplorationData). Exploration data ("explo") and exobiology
("bio") scanned before the mark count as sold, in the FIS and the plugin.

Standard library only.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, Optional, Tuple

__all__ = ["FILE_NAME", "PARTS", "SOLD_PARTS", "load", "load_cached", "mark", "mark_sold", "since",
           "sold_since", "fuel_since", "ship_key", "plugin_path"]

FILE_NAME = "learn_reset.json"
PARTS = ("route", "work", "fuel", "value")
SOLD_PARTS = ("explo", "bio")            # SM1: what a sold mark covers
_LOCK = threading.Lock()
_CACHE: Dict[str, Any] = {"key": None, "data": None}


def plugin_path(plugin_dir: str) -> str:
    """Where the FIS keeps the marks, seen from the plugin folder."""
    return os.path.join(plugin_dir, "FIS", FILE_NAME)


def _empty() -> Dict[str, Any]:
    return {"version": 1, "route": None, "work": None, "value": None, "fuel": {}, "sold": {}}


def load(path: Optional[str]) -> Dict[str, Any]:
    """The marks in the file; an empty set when it is missing or broken."""
    out = _empty()
    if not path:
        return out
    try:
        with open(path, encoding="utf-8") as fh:
            got = json.load(fh)
    except (OSError, ValueError):
        return out
    if not isinstance(got, dict):
        return out
    for part in ("route", "work", "value"):
        if isinstance(got.get(part), (int, float)):
            out[part] = float(got[part])
    if isinstance(got.get("fuel"), dict):
        out["fuel"] = {str(k): float(v) for k, v in got["fuel"].items() if isinstance(v, (int, float))}
    if isinstance(got.get("sold"), dict):
        out["sold"] = _sold_marks(got["sold"])
    return out


def _sold_marks(raw: Dict[Any, Any]) -> Dict[str, Dict[str, float]]:
    """SM1: the sold marks per commander, only the known parts with a number."""
    out: Dict[str, Dict[str, float]] = {}
    for fid, parts in raw.items():
        if isinstance(parts, dict):
            got = {p: float(parts[p]) for p in SOLD_PARTS if isinstance(parts.get(p), (int, float))}
            if got:
                out[str(fid)] = got
    return out


def load_cached(path: Optional[str]) -> Dict[str, Any]:
    """load(), read again only when the file changed (size, mtime) - for the
    plugin, which asks at journal events."""
    try:
        st = os.stat(path) if path else None
    except OSError:
        st = None
    key = (path, st.st_mtime_ns, st.st_size) if st else (path, None, None)
    if _CACHE["key"] != key:
        _CACHE.update(key=key, data=load(path) if st else _empty())
    return _CACHE["data"]


def ship_key(ship: Any) -> str:
    """The fuel model's ship key (commander, ShipID, mass step) as a string."""
    return json.dumps(list(ship) if isinstance(ship, (list, tuple)) else [ship])


def mark(path: str, part: str, ts: Optional[float] = None, ship: Any = None) -> Dict[str, Any]:
    """Reset one model now (or at ts): write the mark, atomically (temporary
    file + os.replace). For "fuel" the mark is per ship. Returns the marks."""
    if part not in PARTS:
        raise ValueError("unknown model: %r" % (part,))
    ts = time.time() if ts is None else float(ts)
    with _LOCK:
        data = load(path)
        if part == "fuel":
            if ship is None:
                raise ValueError("a fuel reset needs the ship")
            data["fuel"][ship_key(ship)] = ts
        else:
            data[part] = ts
        _write(path, data)
    return data


def _write(path: str, data: Dict[str, Any]) -> None:
    # M1: only the FIS writes (under _LOCK), the plugin reads; the temporary
    # name carries the process, so two FIS started by mistake never share it
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, sort_keys=True)
    os.replace(tmp, path)


def mark_sold(path: str, fid: str, ts: Optional[float] = None,
              parts: Tuple[str, ...] = SOLD_PARTS) -> Dict[str, Any]:
    """SM1: the commander's data scanned before ts (default now) counts as
    sold - exploration ("explo") and / or exobiology ("bio")."""
    if not fid or not parts or any(p not in SOLD_PARTS for p in parts):
        raise ValueError("a sold mark needs the commander and its parts")
    ts = time.time() if ts is None else float(ts)
    with _LOCK:
        data = load(path)
        data["sold"].setdefault(str(fid), {}).update({p: ts for p in parts})
        _write(path, data)
    return data


def sold_since(data: Dict[str, Any], fid: Optional[str]) -> Dict[str, float]:
    """SM1: the commander's sold marks ({"explo": ts, "bio": ts}), empty when none."""
    return dict(((data or {}).get("sold") or {}).get(str(fid), {})) if fid else {}


def since(data: Dict[str, Any], part: str) -> Optional[float]:
    """When the route, work or value model was reset, None when never."""
    v = (data or {}).get(part)
    return float(v) if isinstance(v, (int, float)) else None


def fuel_since(data: Dict[str, Any]) -> Dict[Tuple[Any, ...], float]:
    """The fuel resets by ship key tuple, for deepspace.FuelState.since."""
    out: Dict[Tuple[Any, ...], float] = {}
    for k, v in ((data or {}).get("fuel") or {}).items():
        try:
            out[tuple(json.loads(k))] = float(v)
        except (ValueError, TypeError):
            continue
    return out
