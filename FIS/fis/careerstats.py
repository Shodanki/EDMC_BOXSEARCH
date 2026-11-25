# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
STATISTICS, more of the commander's own career (5.1.0, user 24.11.) - from
the journals (with the EDDiscovery archive when it is on), read only:

- ST3 travel in a grid like EDDiscovery's: jumps, light years, new systems
  (never visited before) and bodies scanned per day, week and month (the
  last twelve of each), and since the last docking.
- ST4 ships compared: per ship (by ShipID, named from its Loadout) the light
  years, jumps, systems, bodies scanned, hours in the ship and losses.
- ST5 the bio catalogue: per genus the species and variants analysed, how
  often, when first, and the value of the species where it was sold.
- ST7 play patterns: when you play - active minutes per weekday and hour
  (local time of this computer), sessions and their length, the pauses.
"""
import calendar
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .live import parse_ts

ACTIVE_GAP_S = 30 * 60        # events closer than this count as time in the ship
_SPANS = (("day", 86400), ("week", 7 * 86400))


def _bucket(ts: float, span: str) -> int:
    """The start (Unix time) of the UTC day, ISO week (Monday) or month of ``ts``."""
    if span == "day":
        return int(ts // 86400) * 86400
    if span == "week":
        d = int(ts // 86400)
        return (d - (d + 3) % 7) * 86400          # 1970-01-01 was a Thursday
    g = time.gmtime(ts)
    return calendar.timegm((g.tm_year, g.tm_mon, 1, 0, 0, 0, 0, 0, 0))


def travel(evs: Iterable[Dict[str, Any]], now: Optional[float] = None) -> Dict[str, Any]:
    """ST3: per day / week / month (the last 12 each) jumps, ly, new systems,
    bodies scanned; and the same since the last docking."""
    now = time.time() if now is None else now
    seen_sys, seen_body = set(), set()
    grid: Dict[str, Dict[int, Dict[str, float]]] = {"day": {}, "week": {}, "month": {}}
    dock = {"jumps": 0, "ly": 0.0, "new": 0, "scans": 0, "since": None}
    for e in evs:
        ev, ts = e.get("event"), parse_ts(e.get("timestamp"))
        if ts is None:
            continue
        if ev == "Docked":
            dock = {"jumps": 0, "ly": 0.0, "new": 0, "scans": 0, "since": ts}
            continue
        add = _travel_add(e, ev, seen_sys, seen_body)
        if not add:
            continue
        for k, v in add.items():
            dock[k] += v
        for span in grid:
            cell = grid[span].setdefault(_bucket(ts, span), {"jumps": 0, "ly": 0.0, "new": 0, "scans": 0})
            for k, v in add.items():
                cell[k] += v
    out: Dict[str, Any] = {"since_dock": dict(dock, ly=round(dock["ly"]))}
    for span, cells in grid.items():
        last = _last_buckets(span, now)
        out[span] = [dict({"start": b}, **{k: round(v) for k, v in cells.get(b, {"jumps": 0, "ly": 0, "new": 0,
                                                                                 "scans": 0}).items()}) for b in last]
    return out


def _travel_add(e: Dict[str, Any], ev: str, seen_sys: set, seen_body: set) -> Dict[str, float]:
    if ev == "FSDJump":
        sid = e.get("SystemAddress") or e.get("StarSystem")
        new = sid not in seen_sys
        seen_sys.add(sid)
        return {"jumps": 1, "ly": e.get("JumpDist") or 0.0, "new": 1 if new else 0}
    if ev == "Scan":
        k = (e.get("SystemAddress"), e.get("BodyID"))
        if k not in seen_body:
            seen_body.add(k)
            return {"scans": 1}
    return {}


def _last_buckets(span: str, now: float, n: int = 12) -> List[int]:
    """The starts of the last n days / weeks / months up to now, oldest first."""
    if span in dict(_SPANS):
        step = dict(_SPANS)[span]
        cur = _bucket(now, span)
        return [cur - step * i for i in range(n - 1, -1, -1)]
    g = time.gmtime(now)
    out = []
    y, m = g.tm_year, g.tm_mon
    for _i in range(n):
        out.append(calendar.timegm((y, m, 1, 0, 0, 0, 0, 0, 0)))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return out[::-1]


def ships(evs: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """ST4: per ship flown - ly, jumps, systems, bodies scanned, hours, losses."""
    by: Dict[Any, Dict[str, Any]] = {}
    cur: Optional[Dict[str, Any]] = None
    last_ts: Optional[float] = None
    for e in evs:
        ev, ts = e.get("event"), parse_ts(e.get("timestamp"))
        if ev == "Loadout" and e.get("ShipID") is not None:
            cur = by.setdefault(e["ShipID"], {"id": e["ShipID"], "systems": set(), "jumps": 0, "ly": 0.0, "scans": 0,
                                              "seconds": 0.0, "lost": 0})
            # a blank name (" ") counts as none: the ship type shows instead
            cur.update(name=(e.get("ShipName") or "").strip() or cur.get("name"), type=(e.get("Ship") or "").lower())
        if cur is None or ts is None:
            continue
        if last_ts is not None and 0 < ts - last_ts < ACTIVE_GAP_S:
            cur["seconds"] += ts - last_ts
        last_ts = ts
        _ship_add(cur, e, ev)
    rows = [dict(s, systems=len(s["systems"]), ly=round(s["ly"]), hours=round(s["seconds"] / 3600, 1))
            for s in by.values() if s["jumps"] or s["scans"] or s["seconds"] > 600]
    for r in rows:
        r.pop("seconds")
    return sorted(rows, key=lambda r: -r["ly"])


def _ship_add(cur: Dict[str, Any], e: Dict[str, Any], ev: str) -> None:
    if ev == "FSDJump":
        cur["jumps"] += 1
        cur["ly"] += e.get("JumpDist") or 0.0
        cur["systems"].add(e.get("SystemAddress") or e.get("StarSystem"))
    elif ev == "Scan":
        cur["scans"] += 1
    elif ev == "Died":
        cur["lost"] += 1


def bio_catalogue(evs: Iterable[Dict[str, Any]], values: Optional[Dict[str, Dict[str, int]]] = None
                  ) -> List[Dict[str, Any]]:
    """ST5: per genus the species and variants analysed - most species first."""
    values = values or {}
    genera: Dict[str, Dict[str, Any]] = {}
    for e in evs:
        if e.get("event") != "ScanOrganic" or e.get("ScanType") != "Analyse":
            continue
        g = e.get("Genus_Localised") or e.get("Genus") or "?"
        sp = e.get("Species_Localised") or e.get("Species") or "?"
        ts = parse_ts(e.get("timestamp")) or 0.0
        gen = genera.setdefault(g, {"genus": g, "species": {}})
        s = gen["species"].setdefault(sp, {"species": sp, "variants": set(), "analysed": 0, "first": ts})
        s["analysed"] += 1
        s["first"] = min(s["first"], ts)
        if e.get("Variant_Localised"):
            s["variants"].add(e["Variant_Localised"].split(" - ")[-1])
    out = []
    for gen in genera.values():
        sps = [dict(s, variants=sorted(s["variants"]), value=(values.get(s["species"]) or {}).get("value"))
               for s in gen["species"].values()]
        sps.sort(key=lambda s: -(s["value"] or 0))
        out.append({"genus": gen["genus"], "species": sps, "analysed": sum(s["analysed"] for s in sps)})
    return sorted(out, key=lambda g: (-len(g["species"]), g["genus"]))


SESSION_GAP_S = 30 * 60      # ST7: a longer silence ends a session


def _median(xs: List[float]) -> Optional[float]:
    xs = sorted(xs)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0


def patterns(evs: Iterable[Dict[str, Any]], local: Any = time.localtime) -> Dict[str, Any]:
    """ST7: active minutes per weekday (0 = Monday) and hour in ``local``
    time - the time between two events closer than SESSION_GAP_S, booked to
    the hour the earlier one fell in - and the sessions those gaps cut."""
    grid = [[0.0] * 24 for _d in range(7)]
    lengths: List[float] = []
    pauses: List[float] = []
    prev: Optional[float] = None
    start: Optional[float] = None
    for e in evs:
        ts = parse_ts(e.get("timestamp"))
        if ts is None or (prev is not None and ts < prev):
            continue
        if prev is not None and ts - prev <= SESSION_GAP_S:
            lt = local(prev)
            grid[lt.tm_wday][lt.tm_hour] += (ts - prev) / 60.0
        elif prev is not None:
            lengths.append(prev - (start or prev))
            pauses.append(ts - prev)
            start = ts
        else:
            start = ts
        prev = ts
    if prev is not None:
        lengths.append(prev - (start or prev))
    lengths = [x for x in lengths if x >= 60]
    cells = [[round(m) for m in row] for row in grid]
    days = [sum(row) for row in cells]
    hours = [sum(cells[d][h] for d in range(7)) for h in range(24)]
    return {"grid": cells, "max": max(max(row) for row in cells), "hours": round(sum(days) / 60.0),
            "busy_day": days.index(max(days)) if any(days) else None,
            "busy_hour": hours.index(max(hours)) if any(hours) else None,
            "sessions": len(lengths), "median_s": _median(lengths), "longest_s": max(lengths) if lengths else None,
            "pause_s": _median([p for p in pauses if p <= 14 * 86400])}


def build(evs: List[Dict[str, Any]], values: Optional[Dict[str, Dict[str, int]]] = None,
          now: Optional[float] = None) -> Dict[str, Any]:
    """ST3 + ST4 + ST5 + ST7 for the STATISTICS answer."""
    return {"travel": travel(evs, now), "ships": ships(evs), "bio": bio_catalogue(evs, values),
            "patterns": patterns(evs)}


__all__: Tuple[str, ...] = ("travel", "ships", "bio_catalogue", "patterns", "build")
