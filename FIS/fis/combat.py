# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
M8: combat mode - is the commander fighting (or about to)?

Read only, from what the game writes anyway:

  Status.json  hardpoints deployed (Flags bit 6), in danger (bit 22),
               being interdicted (bit 23)
  journal      UnderAttack (you), ShieldState off, HullDamage of your ship,
               Interdicted, ShipTargeted (a ship locked)

Two levels the views can paint with the theme's tokens:

  alert   being shot at or pulled out of supercruise right now
          (journal hits count for ALERT_S seconds)
  ready   hardpoints out, or a ship locked within TARGET_S seconds while
          the hardpoints are out

`until` tells the browser when the state ends by itself (no new file write
needed to calm down).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

ALERT_S = 30.0
TARGET_S = 60.0
HARDPOINTS, DANGER, INTERDICTED = 6, 22, 23
DOCKED, LANDED, SUPERCRUISE = 0, 1, 4


def _bit(v: Any, n: int) -> bool:
    return bool(int(v or 0) >> n & 1)


def note_event(hits: Dict[str, float], e: Dict[str, Any], ts: Optional[float]) -> bool:
    """Remember the time of a combat event (live.py). True when it was one."""
    if ts is None:
        return False
    ev = e.get("event")
    if ev == "UnderAttack" and e.get("Target", "You") in ("You", None):
        hits["attacked"] = ts
    elif ev == "ShieldState" and not e.get("ShieldsUp", True):
        hits["shields_down"] = ts
    elif ev == "HullDamage" and e.get("PlayerPilot") and not e.get("Fighter"):
        hits["hull_hit"] = ts
    elif ev == "Interdicted":
        hits["interdicted"] = ts
    elif ev == "ShipTargeted" and e.get("TargetLocked"):
        hits["target"] = ts
    elif ev in ("Docked", "Died", "Shutdown", "LoadGame", "Resurrect"):
        hits.clear()                # the fight is over, whatever happened
        return True
    else:
        return False
    return True


def combat_state(live: Dict[str, Any], now: float) -> Dict[str, Any]:
    """{'level': None|'ready'|'alert', 'reasons': [...], 'until': ts|None}."""
    st = live.get("status") or {}
    flags = st.get("flags") or 0
    hits = live.get("combat_hits") or {}
    reasons = []
    until = None
    docked = _bit(flags, DOCKED) or _bit(flags, LANDED)
    for key in ("attacked", "shields_down", "hull_hit", "interdicted"):
        ts = hits.get(key)
        if ts is not None and 0 <= now - ts < ALERT_S and not docked:
            reasons.append(key)
            until = max(until or 0, ts + ALERT_S)
    if _bit(flags, INTERDICTED):
        reasons.append("interdicted_now")
    if _bit(flags, DANGER) and not docked:
        reasons.append("danger")
    level = "alert" if reasons else None
    hardpoints = _bit(flags, HARDPOINTS) and not docked
    if hardpoints:
        reasons.append("hardpoints")
        ts = hits.get("target")
        if ts is not None and 0 <= now - ts < TARGET_S:
            reasons.append("target")
            if level is None:
                until = max(until or 0, ts + TARGET_S)
        level = level or "ready"
    return {"level": level, "reasons": reasons, "until": until}
