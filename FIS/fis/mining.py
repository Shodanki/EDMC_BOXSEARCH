"""
MINING: the last mining session from the journal, and what the tritium you
mined means for the carrier.

A session is the last run of mining events (prospector / collector limpets,
prospected asteroids, refined tonnes) without a break longer than GAP_S. It
is "active" while the last of them is younger than that.

Reads the journal only - ProspectedAsteroid, MiningRefined, LaunchDrone,
AsteroidCracked. Cargo and limpets on board come from Cargo.json (shipview).
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .live import parse_ts

GAP_S = 30 * 60
EVENTS = ("ProspectedAsteroid", "MiningRefined", "LaunchDrone", "AsteroidCracked")


def type_key(typ: Optional[str]) -> str:
    """'$tritium_name;' / 'Tritium' / 'LowTemperatureDiamond' -> 'tritium' ..."""
    s = (typ or "").strip().strip("$;").lower()
    if s.endswith("_name"):
        s = s[:-5]
    return s.replace(" ", "")


def content_level(content: Optional[str]) -> Optional[str]:
    """'$AsteroidMaterialContent_Low;' -> 'low' (medium, high)."""
    s = (content or "").lower()
    for k in ("high", "medium", "low"):
        if k in s:
            return k
    return None


def _asteroid(e: Dict[str, Any]) -> Dict[str, Any]:
    mats = [{"key": type_key(m.get("Name")), "name": m.get("Name_Localised") or m.get("Name"),
             "pct": round(float(m.get("Proportion") or 0), 1)} for m in e.get("Materials") or []]
    mats.sort(key=lambda m: -m["pct"])
    return {"t": parse_ts(e.get("timestamp")), "materials": mats,
            "content": content_level(e.get("Content")), "remaining": e.get("Remaining"),
            "motherlode": e.get("MotherlodeMaterial_Localised") or e.get("MotherlodeMaterial")}


def session(events: List[Dict[str, Any]], now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    now = time.time() if now is None else now
    # repair, fuel or research limpets are no mining
    mev = [e for e in events if e["event"] in EVENTS and parse_ts(e.get("timestamp"))
           and (e["event"] != "LaunchDrone" or (e.get("Type") or "").lower() in ("prospector", "collection"))]
    run: List[Dict[str, Any]] = []
    j = len(mev)
    while j > 0:                       # the last run that refined or prospected something
        i = j - 1
        while i > 0 and parse_ts(mev[i]["timestamp"]) - parse_ts(mev[i - 1]["timestamp"]) <= GAP_S:
            i -= 1
        if any(e["event"] in ("MiningRefined", "ProspectedAsteroid") for e in mev[i:j]):
            run = mev[i:j]
            break
        j = i
    if not run:
        return None
    start, end = parse_ts(run[0]["timestamp"]), parse_ts(run[-1]["timestamp"])
    active = now - end <= GAP_S
    refined: Dict[str, Dict[str, Any]] = {}
    drones = {"prospector": 0, "collection": 0}
    asteroids: List[Dict[str, Any]] = []
    cracked = 0
    for e in run:
        ev = e["event"]
        if ev == "MiningRefined":
            k = type_key(e.get("Type"))
            r = refined.setdefault(k, {"key": k, "name": e.get("Type_Localised") or k.capitalize(), "count": 0})
            r["count"] += 1
        elif ev == "LaunchDrone":
            typ = (e.get("Type") or "").lower()
            drones[typ] += 1
        elif ev == "ProspectedAsteroid":
            asteroids.append(_asteroid(e))
        elif ev == "AsteroidCracked":
            cracked += 1
    hours = max(60.0, (now if active else end) - start) / 3600.0
    total = sum(r["count"] for r in refined.values())
    out_ref = sorted(refined.values(), key=lambda r: -r["count"])
    for r in out_ref:
        r["per_hour"] = round(r["count"] / hours, 1)
    main = out_ref[0]["key"] if out_ref else None
    best = None
    if main and asteroids:
        def share(a):
            return max((m["pct"] for m in a["materials"] if m["key"] == main), default=0.0)
        b = max(asteroids, key=share)
        if share(b) > 0:
            best = dict(b, share=share(b))
    return {
        "start": start, "end": end, "active": active, "minutes": round(hours * 60),
        "refined": out_ref, "total": total, "per_hour": round(total / hours, 1),
        "per_min": round(total / (hours * 60), 2), "main": main,
        "drones": drones, "cracked": cracked, "asteroids": len(asteroids),
        "motherlodes": sum(1 for a in asteroids if a["motherlode"]),
        "last": asteroids[-1] if asteroids else None, "best": best,
        "tritium": refined.get("tritium", {}).get("count", 0),
    }
