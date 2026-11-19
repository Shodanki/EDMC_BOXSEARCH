# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
5.0 CARRIER > JUMP PLAN: the fleet carrier's jumps to a target, planned from
data on this PC, with the time and tritium of every jump.

* time: the countdown (CarrierJumpRequest -> DepartureTime) is learnt from
  the commander's own jumps; the cooldown after a jump is the public value
  (5 min: Elite Dangerous Fandom wiki, "Drake-Class Carrier", read
  19.11.2026). Your fastest next request after an arrival is shown beside it.
* nothing is sent to the game: the commander enters every jump in the
  carrier's galaxy map; the FIS only plans, counts and ticks off.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional

from .live import parse_ts

COOLDOWN_MIN = 5.0          # public value, see the module docstring
COUNTDOWN_PRIOR_MIN = 15.0  # until the first own jump is known
CARRIER_MAX_JUMP = 500.0


def _pct(vals: List[float], p: float) -> float:
    """The p-th percentile (0..1) of sorted values, linear between ranks."""
    if len(vals) == 1:
        return vals[0]
    k = (len(vals) - 1) * p
    lo = int(math.floor(k))
    hi = min(lo + 1, len(vals) - 1)
    return vals[lo] + (vals[hi] - vals[lo]) * (k - lo)


def _countdowns(evs: Iterable[Dict[str, Any]]) -> List[float]:
    """Minutes from each own CarrierJumpRequest to its DepartureTime (the
    request the game kept; a cancelled one still had its countdown)."""
    out = []
    for e in evs:
        if e.get("event") != "CarrierJumpRequest":
            continue
        a, b = parse_ts(e.get("timestamp")), parse_ts(e.get("DepartureTime"))
        if a is not None and b is not None and 0 < b - a < 6 * 3600:
            out.append((b - a) / 60.0)
    return sorted(out)


def _fastest_next(evs: Iterable[Dict[str, Any]]) -> Optional[float]:
    """Minutes from an arrival (the first CarrierJump/CarrierLocation at a
    requested target) to the next request - the shortest seen."""
    target, arrived, best = None, None, None
    for e in evs:
        ev = e.get("event")
        if ev == "CarrierJumpRequest":
            t = parse_ts(e.get("timestamp"))
            if arrived is not None and t is not None and t > arrived:
                gap = (t - arrived) / 60.0
                best = gap if best is None else min(best, gap)
            target, arrived = e.get("SystemName"), None
        elif ev in ("CarrierJump", "CarrierLocation") and target and e.get("StarSystem") == target:
            arrived, target = parse_ts(e.get("timestamp")), None
    return round(best, 1) if best is not None else None


def timing(evs: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """How long a carrier jump takes: countdown learnt from your own jumps
    (median, the middle 80 % as the range, n) and the cooldown."""
    evs = list(evs)
    cd = _countdowns(evs)
    if cd:
        count = {"mid": round(_pct(cd, 0.5), 1), "lo": round(_pct(cd, 0.1), 1),
                 "hi": round(_pct(cd, 0.9), 1), "n": len(cd), "learnt": True}
    else:
        count = {"mid": COUNTDOWN_PRIOR_MIN, "lo": COUNTDOWN_PRIOR_MIN, "hi": COUNTDOWN_PRIOR_MIN,
                 "n": 0, "learnt": False}
    return {"countdown": count, "cooldown": COOLDOWN_MIN, "fastest_next": _fastest_next(evs),
            "per_jump": round(count["mid"] + COOLDOWN_MIN, 1)}


def trip_time(jumps: int, tm: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Minutes for `jumps` carrier jumps: every jump its countdown, every
    one but the last its cooldown (a range from the countdown's range)."""
    if not jumps or jumps < 1:
        return None
    c = tm["countdown"]
    cool = (jumps - 1) * tm["cooldown"]
    return {"jumps": jumps, "mid": round(jumps * c["mid"] + cool), "lo": round(jumps * c["lo"] + cool),
            "hi": round(jumps * c["hi"] + cool), "n": c["n"]}
