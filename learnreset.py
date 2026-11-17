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

Both read the journals again at every start, so forgetting a model means
remembering WHEN it was reset: measurements before that moment are left
out from then on. The marks live in FIS/learn_reset.json, next to fis.ini
(like favourites.json, personal, never in the repository, written only
when the commander presses "reset" in the FIS); the plugin reads the same
file at start-up. A missing or broken file means: nothing was reset.

    {"version": 1, "route": 1794909600.0, "work": null,
     "fuel": {"[\\"Cmdr\\", 9, 37]": 1794909600.0}}

Standard library only.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, Optional, Tuple

__all__ = ["FILE_NAME", "PARTS", "load", "mark", "since", "fuel_since", "ship_key", "plugin_path"]

FILE_NAME = "learn_reset.json"
PARTS = ("route", "work", "fuel")
_LOCK = threading.Lock()


def plugin_path(plugin_dir: str) -> str:
    """Where the FIS keeps the marks, seen from the plugin folder."""
    return os.path.join(plugin_dir, "FIS", FILE_NAME)


def _empty() -> Dict[str, Any]:
    return {"version": 1, "route": None, "work": None, "fuel": {}}


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
    for part in ("route", "work"):
        if isinstance(got.get(part), (int, float)):
            out[part] = float(got[part])
    if isinstance(got.get("fuel"), dict):
        out["fuel"] = {str(k): float(v) for k, v in got["fuel"].items() if isinstance(v, (int, float))}
    return out


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
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1, sort_keys=True)
        os.replace(tmp, path)
    return data


def since(data: Dict[str, Any], part: str) -> Optional[float]:
    """When the route or work model was reset, None when never."""
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
