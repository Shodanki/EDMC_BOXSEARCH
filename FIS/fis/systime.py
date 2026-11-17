# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
TIME PER SYSTEM (5.0, test finding own-4, user 17.11.2026): how long you
spent in each system and on what, set against the route's estimate.

From the journals of the active commander: a visit runs from the arrival
(FSDJump, CarrierJump, Location) to the next one elsewhere, a Shutdown or a
pause of PAUSE_S - the pause does not count. Per system: minutes, visits,
the honk, bodies scanned, maps, species analysed, landings. The estimate is
the plugin's first route estimate once your FSS was complete (table
route_estimates, kept since 5.0 - older systems have none). Read only.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

from .live import parse_ts

PAUSE_S = 30 * 60           # a gap this long ends the visit (as a game session)
MIN_S = 5 * 60              # a system without work counts from this long on
ARRIVALS = ("FSDJump", "CarrierJump", "Location")


def _new(a: int, name: str, t: float) -> Dict[str, Any]:
    return {"id64": a, "name": name, "first": t, "seconds": 0.0, "visits": 0,
            "honk": 0, "scans": set(), "maps": 0, "bio": 0, "landings": 0}


def _count(s: Dict[str, Any], e: Dict[str, Any]) -> None:
    ev = e.get("event")
    if ev == "FSSDiscoveryScan":
        s["honk"] += 1
    elif ev == "Scan" and e.get("ScanType") != "NavBeaconDetail":
        s["scans"].add(e.get("BodyID"))
    elif ev == "SAAScanComplete":
        s["maps"] += 1
    elif ev == "ScanOrganic" and e.get("ScanType") == "Analyse":
        s["bio"] += 1
    elif ev == "Touchdown":
        s["landings"] += 1


def _open(out: Dict[int, Dict[str, Any]], here: tuple, t: float, arrival: bool) -> Dict[str, Any]:
    s = out.setdefault(here[0], _new(here[0], here[1], t))
    s["visits"] += 1 if arrival else 0
    return s


def visits(evs: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    """id64 -> time and work in that system, summed over the visits; after
    a pause in the same system the time runs on from the next event."""
    out: Dict[int, Dict[str, Any]] = {}
    cur: Optional[Dict[str, Any]] = None
    here: Optional[tuple] = None
    start = last = 0.0
    for e in evs:
        t = parse_ts(e.get("timestamp"))
        if t is None:
            continue
        ev = e.get("event")
        arrival = ev in ARRIVALS and bool(e.get("SystemAddress"))
        if cur is not None and (t - last > PAUSE_S or ev == "Shutdown"
                                or (arrival and e["SystemAddress"] != cur["id64"])):
            cur["seconds"] += last - start
            cur = None
        if ev == "Shutdown":
            here = None
        elif arrival:
            here = (e["SystemAddress"], e.get("StarSystem") or "?")
        if cur is None and here is not None:
            cur, start = _open(out, here, t, arrival), t
        if cur is not None:
            _count(cur, e)
        last = t
    if cur is not None:
        cur["seconds"] += last - start
    return out


def estimates(db: Any, fid: Optional[str]) -> Dict[int, Dict[str, Any]]:
    """The plugin's kept estimates of one commander (none before 5.0)."""
    if db is None or not fid:
        return {}
    try:
        rows = db.query("SELECT sys_id64, ts, total_s, travel_s, work_s, stops FROM route_estimates WHERE fid=?",
                        (fid,))
    except sqlite3.Error:
        return {}
    return {r["sys_id64"]: dict(r) for r in rows}


def _median(xs: List[float]) -> Optional[float]:
    xs = sorted(xs)
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2.0


def build(evs: List[Dict[str, Any]], db: Any = None, fid: Optional[str] = None, keep: int = 40) -> Dict[str, Any]:
    """The card: the last `keep` systems you worked in, newest first, with
    the estimate where one was kept, and the median of time / estimate."""
    est = estimates(db, fid)
    rows = []
    for s in visits(evs).values():
        work = s["maps"] + s["bio"] + s["landings"] + s["honk"]
        if not work and s["seconds"] < MIN_S:
            continue                     # passing through
        e = est.get(s["id64"])
        minutes = round(s["seconds"] / 60.0, 1)
        rows.append({"id64": s["id64"], "name": s["name"], "first": s["first"], "minutes": minutes,
                     "visits": s["visits"], "honk": s["honk"], "scans": len(s["scans"]), "maps": s["maps"],
                     "bio": s["bio"], "landings": s["landings"],
                     "estimate": round(e["total_s"] / 60.0, 1) if e else None,
                     "stops": e["stops"] if e else None,
                     "ratio": round(s["seconds"] / e["total_s"], 2) if e and e["total_s"] else None})
    rows.sort(key=lambda r: -r["first"])
    with_est = [r["ratio"] for r in rows if r["ratio"] is not None]
    return {"systems": rows[:keep], "n": len(rows), "hours": round(sum(r["minutes"] for r in rows) / 60.0, 1),
            "median_min": _median([r["minutes"] for r in rows]),
            "ratio": _median(with_est), "ratio_n": len(with_est)}


def here(v: Optional[Dict[str, Any]], est: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """SYSTEM: this system so far (visits()) against its kept estimate."""
    if v is None and est is None:
        return None
    sec = v["seconds"] if v else 0.0
    return {"minutes": round(sec / 60.0, 1), "visits": v["visits"] if v else 0,
            "maps": v["maps"] if v else 0, "bio": v["bio"] if v else 0, "landings": v["landings"] if v else 0,
            "estimate": round(est["total_s"] / 60.0, 1) if est else None,
            "ratio": round(sec / est["total_s"], 2) if est and est["total_s"] and sec else None}
