# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
4.12: ground mining in the SRV Rhino - the rig being collected, and the
two limits: the Rhino's hold, and the ship's hold the Rhino's load goes
into when it docks.

From the journal alone (developer's session 14.11.2026): LaunchSRV names
the vehicle (SRVType "mev_rhino"), every tonne collected writes one
MiningRefined (1-2 s apart while you drive over a rig), Cargo with
Vessel "SRV" / "Ship" gives each hold's load, Loadout the ship's cargo
capacity. Placing a rig writes nothing, so a rig is the run of tonnes
without a pause longer than RIG_GAP_S - or a full one (RIG_FULL_T).

What still fits is the smaller of: the Rhino's free room, and what the
ship has free once the Rhino's load is aboard; full rigs count at 12 t.

No EDMC imports: the plugin's overlay and the FIS use the same numbers.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

RHINO_CAPACITY_T = 72      # the SRV Rhino's hold (Frontier)
RIG_FULL_T = 12            # a full rig: 12 chunks of one tonne
RIG_GAP_S = 8.0            # the same as surfacenav.RIG_GAP_S: a longer pause is another rig
EVENTS = ("Loadout", "Cargo", "LaunchSRV", "DockSRV", "SRVDestroyed", "MiningRefined")
SRV_FLAG = 1 << 26         # Status.json Flags: in the SRV

Line = Tuple[str, str]


def is_rhino(e: Dict[str, Any]) -> bool:
    """True for a LaunchSRV of the Rhino."""
    return "rhino" in ("%s %s" % (e.get("SRVType") or "", e.get("SRVType_Localised") or "")).lower()


class GroundMine:
    """One Rhino trip: the rigs collected, the Rhino's and the ship's hold."""

    def __init__(self) -> None:
        self.ship_capacity: Optional[int] = None
        self.ship_cargo: Optional[int] = None
        self.in_rhino = False
        self.srv_cargo: Optional[int] = None
        self.rigs: List[int] = []          # tonnes per rig of this trip, in order
        self.last_t: Optional[float] = None

    def feed(self, e: Dict[str, Any], ts: Optional[float]) -> bool:
        """One journal event; True when the block should be drawn again."""
        ev = e.get("event")
        if ev == "Loadout":
            self.ship_capacity = int(e.get("CargoCapacity") or 0)
        elif ev == "Cargo":
            return self._cargo(e)
        elif ev == "LaunchSRV":
            self.in_rhino = is_rhino(e)
            self.rigs, self.last_t = [], None
            self.srv_cargo = 0 if self.in_rhino else None
            return self.in_rhino
        elif ev in ("DockSRV", "SRVDestroyed"):
            was = self.in_rhino
            self.in_rhino, self.rigs, self.last_t, self.srv_cargo = False, [], None, None
            return was
        elif ev == "MiningRefined" and self.in_rhino:
            self._tonne(ts)
            return True
        return False

    def _cargo(self, e: Dict[str, Any]) -> bool:
        """A hold's load: the ship's, or the SRV's while out in it."""
        n = e.get("Count")
        if n is None:
            return False
        if e.get("Vessel") == "Ship":
            self.ship_cargo = int(n)
            return False
        if e.get("Vessel") == "SRV" and self.in_rhino:
            self.srv_cargo = int(n)
            return True
        return False

    def _tonne(self, ts: Optional[float]) -> None:
        """One tonne collected: the same rig, or the next."""
        new = (not self.rigs or self.last_t is None or ts is None
               or ts - self.last_t > RIG_GAP_S or self.rigs[-1] >= RIG_FULL_T)
        if new:
            self.rigs.append(0)
        self.rigs[-1] += 1
        if ts is not None:
            self.last_t = ts

    def status(self, entry: Dict[str, Any]) -> None:
        """Status.json: in the SRV its Cargo is the SRV's load (between events)."""
        try:
            flags = int(entry.get("Flags") or 0)
        except (TypeError, ValueError):
            return
        if self.in_rhino and flags & SRV_FLAG and entry.get("Cargo") is not None:
            try:
                self.srv_cargo = int(round(float(entry["Cargo"])))
            except (TypeError, ValueError):
                pass

    def replay(self, events: Iterable[Tuple[Dict[str, Any], Optional[float]]]) -> "GroundMine":
        """Feed (event, time) pairs - the newest journal at a start in the field."""
        for e, ts in events:
            if e.get("event") in EVENTS:
                self.feed(e, ts)
        return self

    def room(self) -> Dict[str, Any]:
        """The two limits and what still fits: rhino_used, rhino_free,
        ship_capacity / ship_cargo / ship_free_after (when known), room,
        room_rigs, limit ("rhino" or "ship"), short (no full rig fits)."""
        used = int(self.srv_cargo or 0)
        free = max(0, RHINO_CAPACITY_T - used)
        out: Dict[str, Any] = {"rhino_capacity": RHINO_CAPACITY_T, "rhino_used": used, "rhino_free": free,
                               "rig_t": RIG_FULL_T, "ship_capacity": self.ship_capacity,
                               "ship_cargo": self.ship_cargo, "ship_free_after": None}
        room, limit = free, "rhino"
        if self.ship_capacity and self.ship_cargo is not None:
            after = max(0, self.ship_capacity - self.ship_cargo - used)
            out["ship_free_after"] = after
            if after < free:
                room, limit = after, "ship"
        out.update(room=room, room_rigs=room // RIG_FULL_T, limit=limit, short=room < RIG_FULL_T)
        return out

    def rig(self, now: Optional[float] = None) -> Dict[str, Any]:
        """The rig being (or last) collected: its number, its tonnes, whether
        you are on it now, and the trip's tonnes."""
        on = bool(self.rigs) and self.last_t is not None and now is not None and now - self.last_t <= 4 * RIG_GAP_S
        return {"n": len(self.rigs), "t": self.rigs[-1] if self.rigs else 0, "collecting": on,
                "trip_t": sum(self.rigs)}

    def lines(self, now: Optional[float] = None, col: Optional[Dict[str, str]] = None) -> List[Line]:
        """The ground mining block for the overlay: rig, Rhino, ship."""
        c = {"head": "#ffb000", "data": "#e0e0e0", "dim": "#9a9a9a", "warn": "#ffcc33", "alert": "#ff5050"}
        c.update(col or {})
        r, g = self.room(), self.rig(now)
        if g["n"]:
            head = ("RHINO > rig %d · %d/%d t   trip %d t" % (g["n"], g["t"], RIG_FULL_T, g["trip_t"])
                    if g["collecting"] else "RHINO > %d rig%s · %d t this trip"
                    % (g["n"], "" if g["n"] == 1 else "s", g["trip_t"]))
        else:
            head = "RHINO > no rig collected yet"
        out: List[Line] = [(head, c["head"])]
        rhino_tight = r["limit"] == "rhino" and r["short"]
        out.append(("HOLD   %d/%d t · %d t free · %d full rig%s"
                    % (r["rhino_used"], r["rhino_capacity"], r["rhino_free"], r["rhino_free"] // RIG_FULL_T,
                       "" if r["rhino_free"] // RIG_FULL_T == 1 else "s"),
                    c["warn"] if rhino_tight else c["data"]))
        if r["ship_free_after"] is not None:
            ship_tight = r["limit"] == "ship"
            # as bright as HOLD: dimmed it was easy to miss beside the compass
            out.append(("SHIP   %d t free with the Rhino's %d t aboard" % (r["ship_free_after"], r["rhino_used"]),
                        c["alert"] if ship_tight and r["short"] else c["warn"] if ship_tight else c["data"]))
        else:
            out.append(("SHIP   hold not known yet - no Loadout / ship Cargo seen", c["dim"]))
        if r["short"]:
            out.append(("%s full - make room before the next rig" % ("SHIP" if r["limit"] == "ship" else "RHINO"),
                        c["alert"]))
        elif r["limit"] == "ship":
            out.append(("LIMIT  the ship: %d t more (%d full rig%s)"
                        % (r["room"], r["room_rigs"], "" if r["room_rigs"] == 1 else "s"), c["warn"]))
        return out
