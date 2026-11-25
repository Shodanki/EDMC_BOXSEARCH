# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
ST14 (5.1.0, user 25.11.): the trip report - one page for a span the
commander picks ("expedition from ... to ..."), printable: the way (jumps,
light years, systems, the new ones, the farthest point, the longest jump,
the regions), the finds (bodies scanned, first discoveries, maps, first
maps, species analysed), the money (income and costs booked, as GAIN /
LOSS counts them), the time played, and the route as points for a map.

From the journals (with the EDDiscovery archive when it is on), read only.
"""
import math
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .live import parse_ts

ARRIVE = ("FSDJump", "CarrierJump", "Location")
ROUTE_POINTS = 400
ACTIVE_GAP_S = 30 * 60
MAX_DAYS = 3660                    # a span longer than ten years is no trip


def parse_day(s: Any) -> Optional[float]:
    """'2026-11-01' -> Unix time of that UTC midnight, or None."""
    try:
        d = datetime.strptime(str(s)[:10], "%Y-%m-%d")
    except (TypeError, ValueError):
        return None
    return d.replace(tzinfo=timezone.utc).timestamp()


def _dist(p: Any) -> Optional[float]:
    if not isinstance(p, (list, tuple)) or len(p) != 3:
        return None
    try:
        return math.sqrt(sum(float(v) ** 2 for v in p))
    except (TypeError, ValueError):
        return None


def _thin(pts: List[Any], keep: int = ROUTE_POINTS) -> List[Any]:
    if len(pts) <= keep:
        return pts
    step = len(pts) / float(keep - 1)
    return [pts[int(i * step)] for i in range(keep - 1)] + [pts[-1]]


class _Way:
    """The way through the span: jumps, ly, systems, extremes, regions, route."""

    def __init__(self, before: set, region_of: Optional[Callable[[Any], Any]]) -> None:
        self.before, self.region_of = before, region_of
        self.jumps, self.ly, self.systems, self.new = 0, 0.0, set(), set()
        self.far: Tuple[float, Optional[str]] = (0.0, None)
        self.longest: Tuple[float, Optional[str]] = (0.0, None)
        self.regions: List[str] = []
        self.route: List[List[float]] = []

    def feed(self, e: Dict[str, Any]) -> None:
        """One arrival (FSDJump, CarrierJump, Location)."""
        if e.get("event") == "FSDJump":
            self.jumps += 1
            d = float(e.get("JumpDist") or 0)
            self.ly += d
            if d > self.longest[0]:
                self.longest = (d, e.get("StarSystem"))
        sid = e.get("SystemAddress") or e.get("StarSystem")
        self.systems.add(sid)
        if sid not in self.before:
            self.new.add(sid)
        pos = e.get("StarPos")
        r = _dist(pos)
        if r is not None:
            if r > self.far[0]:
                self.far = (r, e.get("StarSystem"))
            self.route.append([round(float(pos[0]), 1), round(float(pos[2]), 1)])
            reg = self.region_of(*pos) if self.region_of else None
            name = reg[1] if isinstance(reg, (list, tuple)) and len(reg) > 1 else None
            if name and name not in self.regions:
                self.regions.append(name)

    def result(self) -> Dict[str, Any]:
        """The way as the report shows it."""
        return {"jumps": self.jumps, "ly": round(self.ly), "systems": len(self.systems), "new_systems": len(self.new),
                "farthest": {"ly": round(self.far[0]), "system": self.far[1]},
                "longest": {"ly": round(self.longest[0], 1), "system": self.longest[1]},
                "regions": self.regions, "route": _thin(self.route)}


def _finds(rng: List[Dict[str, Any]], mapped_before: Dict[Tuple[Any, Any], Any]) -> Dict[str, Any]:
    """Bodies scanned, first discoveries, maps and first maps, species analysed."""
    scanned, first, maps, first_maps, species = set(), set(), 0, 0, set()
    analysed = 0
    for e in rng:
        ev = e.get("event")
        key = (e.get("SystemAddress"), e.get("BodyID"))
        if ev == "Scan" and e.get("ScanType") in ("Detailed", "AutoScan", "Basic") and key[1] is not None:
            scanned.add(key)
            if e.get("WasDiscovered") is False and not str(e.get("BodyName") or "").endswith(("Ring", "Belt")):
                first.add(key)
        elif ev == "SAAScanComplete":
            maps += 1
            first_maps += 1 if mapped_before.get(key) is False else 0
        elif ev == "ScanOrganic" and e.get("ScanType") == "Analyse":
            analysed += 1
            species.add(e.get("Species_Localised") or e.get("Species"))
    return {"bodies": len(scanned), "first_discovered": len(first), "maps": maps, "first_maps": first_maps,
            "analysed": analysed, "species": len(species)}


def _active_h(rng: List[Dict[str, Any]]) -> float:
    s, prev = 0.0, None
    for e in rng:
        ts = parse_ts(e.get("timestamp"))
        if ts is None:
            continue
        if prev is not None and 0 <= ts - prev <= ACTIVE_GAP_S:
            s += ts - prev
        prev = ts
    return round(s / 3600.0, 1)


def build(evs: Iterable[Dict[str, Any]], start: float, end: float,
          region_of: Optional[Callable[[Any], Any]] = None) -> Dict[str, Any]:
    """The report for [start, end) (Unix time)."""
    from . import ledger
    before: set = set()
    was_mapped: Dict[Tuple[Any, Any], Any] = {}
    rng: List[Dict[str, Any]] = []
    for e in evs:
        ts = parse_ts(e.get("timestamp"))
        if ts is None:
            continue
        if e.get("event") == "Scan":
            was_mapped.setdefault((e.get("SystemAddress"), e.get("BodyID")), e.get("WasMapped"))
        if ts < start:
            if e.get("event") in ARRIVE:
                before.add(e.get("SystemAddress") or e.get("StarSystem"))
        elif ts < end:
            rng.append(e)
    way = _Way(before, region_of)
    for e in rng:
        if e.get("event") in ARRIVE:
            way.feed(e)
    money = ledger.build_ledger(rng)["totals"] if rng else {"income": 0, "costs": 0, "net": 0}
    first_ts = parse_ts(rng[0].get("timestamp")) if rng else None
    last_ts = parse_ts(rng[-1].get("timestamp")) if rng else None
    return {"start": start, "end": end, "first": first_ts, "last": last_ts, "events": len(rng),
            "hours": _active_h(rng), "way": way.result(), "finds": _finds(rng, was_mapped),
            "money": {k: money.get(k, 0) for k in ("income", "costs", "net")}}
