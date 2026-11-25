# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
STATISTICS > RECORDS & ATLAS (5.1.0, user 24.11.): from the commander's own
journals (with the EDDiscovery archive when it is switched on), read only.

- ST2 personal records: the biggest, heaviest and hottest star scanned, the
  biggest, smallest and heaviest planet, the highest gravity scanned and
  landed on, the hottest and coldest planet, the fastest spinning body, the
  longest jump, the farthest point from Sol, the most jumps in one day.
- ST6 regions: the galaxy's 42 regions (RegionMap) visited - jumps, systems,
  first and last visit, biological codex entries there.
- ST8 stars and worlds: the arrival stars by class; Earth-likes, water and
  ammonia worlds and terraformable planets scanned, and how many of them
  nobody had discovered before.
- ST9 the way through the galaxy: the distance to Sol at the end of each day
  and the light years jumped.

Each body counts once (system address + body id); all time, not the period.
"""
import math
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .live import parse_ts

SUN_RADIUS_M = 695_700_000.0
G = 9.80665
# star classes grouped for the table: journal StarType -> group
_STAR_GROUP = {"O": "O", "B": "B", "A": "A", "F": "F", "G": "G", "K": "K", "M": "M",
               "L": "brown dwarf", "T": "brown dwarf", "Y": "brown dwarf",
               "TTS": "T Tauri", "AeBe": "Herbig Ae/Be", "N": "neutron star", "H": "black hole",
               "SupermassiveBlackHole": "black hole", "C": "carbon", "CN": "carbon", "CJ": "carbon", "CH": "carbon",
               "CHd": "carbon", "MS": "S/MS", "S": "S/MS", "X": "exotic"}
WORLDS = ("Earthlike body", "Water world", "Ammonia world")
Region = Callable[[float, float, float], Optional[Tuple[int, str]]]


def star_group(star_type: Optional[str]) -> str:
    """The table group of a journal StarType ("K_OrangeGiant" counts as K giant)."""
    t = star_type or "?"
    if t.startswith("D"):
        return "white dwarf"
    if t.startswith("W"):
        return "Wolf-Rayet"
    if "Giant" in t or "SuperGiant" in t:
        return t.split("_")[0] + " giant"
    return _STAR_GROUP.get(t, t)


class _Rec:
    """The best value per record, with where and when."""

    def __init__(self) -> None:
        self.best: Dict[str, Dict[str, Any]] = {}

    def offer(self, key: str, value: Any, e: Dict[str, Any], low: bool = False, **where: Any) -> None:
        """Keep ``value`` from event ``e`` when it beats the record (``low``: the smaller wins)."""
        if value is None:
            return
        cur = self.best.get(key)
        if cur is None or (value < cur["value"] if low else value > cur["value"]):
            self.best[key] = dict({"key": key, "value": value, "body": e.get("BodyName") or e.get("Body"),
                                   "system": e.get("StarSystem"), "id64": e.get("SystemAddress"),
                                   "ts": parse_ts(e.get("timestamp"))}, **where)


RECORD_ORDER = ("star_biggest", "star_heaviest", "star_hottest", "planet_biggest", "planet_smallest",
                "planet_heaviest", "gravity_scanned", "gravity_landed", "planet_hottest", "planet_coldest",
                "spin_fastest", "jump_longest", "farthest_sol", "jumps_one_day")


def _scan(rec: _Rec, e: Dict[str, Any], grav: Dict[Tuple[Any, Any], float]) -> None:
    radius, temp = e.get("Radius"), e.get("SurfaceTemperature")
    if e.get("StarType"):
        rec.offer("star_biggest", round(radius / SUN_RADIUS_M, 2) if radius else None, e)
        rec.offer("star_heaviest", e.get("StellarMass"), e)
        rec.offer("star_hottest", round(temp) if temp else None, e)
    elif e.get("PlanetClass"):
        rec.offer("planet_biggest", round(radius / 1000) if radius else None, e)
        rec.offer("planet_smallest", round(radius / 1000) if radius else None, e, low=True)
        rec.offer("planet_heaviest", e.get("MassEM"), e)
        g = e.get("SurfaceGravity")
        if g:
            grav[(e.get("SystemAddress"), e.get("BodyID"))] = round(g / G, 2)
            rec.offer("gravity_scanned", round(g / G, 2), e)
        rec.offer("planet_hottest", round(temp) if temp else None, e)
        rec.offer("planet_coldest", round(temp) if temp else None, e, low=True)
    spin = e.get("RotationPeriod")
    if spin:
        rec.offer("spin_fastest", round(abs(spin), 2), e, low=True)


def _jump(rec: _Rec, e: Dict[str, Any], days: Dict[int, int]) -> None:
    rec.offer("jump_longest", round(e["JumpDist"], 2) if e.get("JumpDist") else None, e)
    p = e.get("StarPos")
    if p:
        rec.offer("farthest_sol", round(math.sqrt(p[0] ** 2 + p[1] ** 2 + p[2] ** 2), 1), e)
    ts = parse_ts(e.get("timestamp"))
    if ts:
        d = int(ts // 86400)
        days[d] = days.get(d, 0) + 1


def personal_records(evs: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """ST2: the records in RECORD_ORDER that the journals hold."""
    rec, grav, days, seen = _Rec(), {}, {}, set()
    landed: List[Dict[str, Any]] = []
    for e in evs:
        ev = e.get("event")
        if ev == "Scan":
            k = (e.get("SystemAddress"), e.get("BodyID"))
            if k not in seen:
                seen.add(k)
                _scan(rec, e, grav)
        elif ev == "FSDJump":
            _jump(rec, e, days)
        elif ev == "Touchdown" and e.get("PlayerControlled", True):
            landed.append(e)
    for e in landed:
        rec.offer("gravity_landed", grav.get((e.get("SystemAddress"), e.get("BodyID"))), e)
    if days:
        d, n = max(days.items(), key=lambda kv: (kv[1], kv[0]))
        rec.best["jumps_one_day"] = {"key": "jumps_one_day", "value": n, "ts": d * 86400.0,
                                     "body": None, "system": None, "id64": None}
    return [rec.best[k] for k in RECORD_ORDER if k in rec.best]


def regions(evs: Iterable[Dict[str, Any]], region_of: Optional[Region],
            names: Iterable[str] = ()) -> Dict[str, Any]:
    """ST6: the regions visited, most jumps first, and those not yet."""
    names = [n for n in names if n]
    if region_of is None:
        return {"visited": [], "total": len(names) or 42, "unvisited": names}
    by: Dict[str, Dict[str, Any]] = {}
    sys_region: Dict[Any, str] = {}
    for e in evs:
        ev = e.get("event")
        if ev == "FSDJump" and e.get("StarPos"):
            r = region_of(*e["StarPos"])
            if not r:
                continue
            ts = parse_ts(e.get("timestamp")) or 0.0
            a = by.setdefault(r[1], {"name": r[1], "jumps": 0, "systems": set(), "first": ts, "last": ts, "bio": 0})
            a["jumps"] += 1
            # the EDDiscovery archive's old jumps carry no SystemAddress: the name then
            a["systems"].add(e.get("SystemAddress") or e.get("StarSystem"))
            a["first"], a["last"] = min(a["first"], ts), max(a["last"], ts)
            sys_region[e.get("SystemAddress")] = r[1]
        elif ev == "CodexEntry" and sys_region.get(e.get("SystemAddress")):
            by[sys_region[e["SystemAddress"]]]["bio"] += 1
    rows = [dict(a, systems=len(a["systems"])) for a in by.values()]
    rows.sort(key=lambda a: -a["jumps"])
    return {"visited": rows, "total": len(names) or 42, "unvisited": [n for n in names if n not in by]}


def stars_and_worlds(evs: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """ST8: arrival stars by class; notable worlds and how many were new."""
    stars: Dict[str, int] = {}
    worlds = {w: {"found": 0, "first": 0} for w in WORLDS + ("terraformable",)}
    seen = set()
    for e in evs:
        if e.get("event") != "Scan":
            continue
        k = (e.get("SystemAddress"), e.get("BodyID"))
        if k in seen:
            continue
        seen.add(k)
        if e.get("StarType") and e.get("DistanceFromArrivalLS") == 0:
            g = star_group(e["StarType"])
            stars[g] = stars.get(g, 0) + 1
        kinds = [e.get("PlanetClass")] if e.get("PlanetClass") in WORLDS else []
        if e.get("TerraformState") == "Terraformable":
            kinds.append("terraformable")
        for w in kinds:
            worlds[w]["found"] += 1
            worlds[w]["first"] += 0 if e.get("WasDiscovered", True) else 1
    return {"stars": sorted(({"group": g, "n": n} for g, n in stars.items()), key=lambda s: -s["n"]),
            "worlds": [dict(kind=w, **worlds[w]) for w in WORLDS + ("terraformable",)]}


def journey(evs: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """ST9: per UTC day the distance to Sol at its last jump; ly jumped."""
    day_dist: Dict[int, float] = {}
    ly = 0.0
    for e in evs:
        if e.get("event") != "FSDJump" or not e.get("StarPos"):
            continue
        ts = parse_ts(e.get("timestamp"))
        if not ts:
            continue
        p = e["StarPos"]
        day_dist[int(ts // 86400)] = math.sqrt(p[0] ** 2 + p[1] ** 2 + p[2] ** 2)
        ly += e.get("JumpDist") or 0.0
    pts = [[d * 86400.0, round(v, 1)] for d, v in sorted(day_dist.items())]
    return {"points": pts, "ly": round(ly), "days": len(pts),
            "now": pts[-1][1] if pts else None, "max": max((p[1] for p in pts), default=None)}


def build(evs: List[Dict[str, Any]], region_of: Optional[Region] = None, region_names: Iterable[str] = (),
          now: Optional[float] = None) -> Dict[str, Any]:
    """The RECORDS & ATLAS answer."""
    return {"generated": time.time() if now is None else now, "records": personal_records(evs),
            "regions": regions(evs, region_of, region_names), "stars": stars_and_worlds(evs),
            "journey": journey(evs)}
