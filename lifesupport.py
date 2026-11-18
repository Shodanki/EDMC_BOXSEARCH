# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
Life support off (5.0, R8, user 18.11.2026 while repairing with the AFMU):
the game writes no event and no Status.json flag when the commander
switches life support off - only DANGER (Flags bit 22) lights. What it
does write:

- a Loadout with the LifeSupport module ``On: false`` or ``Health: 0``
  (sure - but after switching in the right panel no Loadout comes);
- ModulesInfo.json after a ModuleInfo, the LifeSupport slot missing or at
  power 0 (sure, while that file is newer than the Loadout);
- ModuleInfo / AfmuRepairs: the AFMU only repairs modules that are switched
  off, so an AfmuRepairs on Life Support says it was off. With DANGER lit
  in the ship and no other cause (heat, interdiction) shortly after such a
  repair session it is "probably off" - shown with a question mark.

Pure and shared: the plugin's overlay line and the FIS SHIP panel ask the
same ``judge``. Read only - nothing is sent to the game. No oxygen time
left: the journal does not say how much is left, so none is guessed.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

Line = Tuple[str, str]

DOCKED, OVERHEATING, DANGER, INTERDICTED, IN_SHIP = 1 << 0, 1 << 20, 1 << 22, 1 << 23, 1 << 24
SERVICE_S = 20 * 60          # a repair session counts this long after its last ModuleInfo / AfmuRepairs
REPAIRED_S = 2 * 3600        # an AFMU repair of the life support itself counts this long
RED = "#FF4040"

__all__ = ["judge", "is_life_support", "overlay_lines", "LifeSupportWatch"]


def is_life_support(name: Any) -> bool:
    """Slot, item or AFMU module name of the life support."""
    n = str(name or "").lower().replace("_", "")
    return "lifesupport" in n


def _ls_module(modules: Iterable[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for m in modules or []:
        if is_life_support(m.get("Slot")) or is_life_support(m.get("Item")):
            return m
    return None


def _sure_off(loadout: Optional[Dict[str, Any]], info: Optional[Dict[str, Any]],
              loadout_ts: Optional[float], info_ts: Optional[float]) -> Optional[str]:
    m = _ls_module((loadout or {}).get("Modules") or [])
    if m is not None and (m.get("On") is False or m.get("Health") == 0):
        return "loadout"
    if info and info.get("Modules") and info_ts is not None and (loadout_ts is None or info_ts >= loadout_ts):
        i = _ls_module(info["Modules"])
        if m is not None and (i is None or not i.get("Power")):
            return "modules"
    return None


def judge(flags: Any, loadout: Optional[Dict[str, Any]] = None, info: Optional[Dict[str, Any]] = None,
          service: Iterable[Tuple[float, str, Any]] = (), now: float = 0.0,
          loadout_ts: Optional[float] = None, info_ts: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Is life support off? None, or {"state": "off" | "probable", "why":
    "loadout" | "modules" | "afmu"}. ``service`` holds (ts, event, module)
    of ModuleInfo / AfmuRepairs since the last Loadout. Only in the ship
    and not docked."""
    try:
        flags = int(flags or 0)
    except (TypeError, ValueError):
        return None
    if not flags & IN_SHIP or flags & DOCKED:
        return None
    why = _sure_off(loadout, info, loadout_ts, info_ts)
    if why:
        return {"state": "off", "why": why}
    if not flags & DANGER or flags & (OVERHEATING | INTERDICTED):
        return None
    sv = [s for s in service if s and s[0] is not None]
    if any(ev == "AfmuRepairs" and is_life_support(mod) and now - t <= REPAIRED_S for t, ev, mod in sv) \
            or any(now - t <= SERVICE_S for t, _ev, _mod in sv):
        return {"state": "probable", "why": "afmu"}
    return None


def overlay_lines(verdict: Optional[Dict[str, Any]]) -> List[Line]:
    """The overlay's left line for a verdict - empty when life support is on."""
    if not verdict:
        return []
    return [("LIFE SUPPORT OFF" + ("" if verdict["state"] == "off" else "?"), RED)]


class LifeSupportWatch:
    """The plugin's memory for ``judge``: the last Loadout and the repair
    events since then. Fed every journal event, asked with Status.json."""

    def __init__(self) -> None:
        self.loadout: Optional[Dict[str, Any]] = None
        self.service: List[Tuple[float, str, Any]] = []
        self.last: Optional[str] = None

    def feed(self, ev: str, entry: Dict[str, Any], ts: Optional[float]) -> None:
        """Note a Loadout, ModuleInfo or AfmuRepairs; a new game forgets."""
        if ev == "Loadout":
            self.loadout, self.service = entry, []
        elif ev in ("ModuleInfo", "AfmuRepairs") and ts is not None:
            self.service.append((ts, ev, entry.get("Module")))
            del self.service[:-40]
        elif ev in ("LoadGame", "Died", "Resurrect"):
            self.loadout, self.service = None, []

    def check(self, flags: Any, now: float) -> Tuple[Optional[Dict[str, Any]], bool]:
        """The verdict now, and whether it changed since the last check."""
        v = judge(flags, self.loadout, None, self.service, now)
        key = v["state"] if v else None
        changed, self.last = key != self.last, key
        return v, changed
