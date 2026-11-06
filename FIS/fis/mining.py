"""
MINING: the last mining session from the journal, and what the tritium you
mined means for the carrier.

A session is the last run of mining events (prospector / collector limpets,
prospected asteroids, refined tonnes) without a break longer than GAP_S. It
is "active" while the last of them is younger than that.

build_mining bundles everything for the MINING view: the session, tritium
for the carrier (tank, ship, mined, delivered), every session so far, the
mined goods with what selling them earned against the carrier's upkeep, the
nearest ring hotspots (plugin database) and the mining ships of the fleet.

Reads the journal, Cargo.json and the plugin database - nothing else.
"""

from __future__ import annotations

import math
import os
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


def _runs(events: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Mining events in runs without a break longer than GAP_S; only runs
    that refined or prospected something (repair, fuel or research limpets
    are no mining)."""
    mev = [e for e in events if e["event"] in EVENTS and parse_ts(e.get("timestamp"))
           and (e["event"] != "LaunchDrone" or (e.get("Type") or "").lower() in ("prospector", "collection"))]
    runs: List[List[Dict[str, Any]]] = []
    cur: List[Dict[str, Any]] = []
    for e in mev:
        if cur and parse_ts(e["timestamp"]) - parse_ts(cur[-1]["timestamp"]) > GAP_S:
            runs.append(cur)
            cur = []
        cur.append(e)
    if cur:
        runs.append(cur)
    return [r for r in runs if any(e["event"] in ("MiningRefined", "ProspectedAsteroid") for e in r)]


def session(events: List[Dict[str, Any]], now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    runs = _runs(events)
    return _summary(runs[-1], now) if runs else None


def sessions(events: List[Dict[str, Any]], now: Optional[float] = None) -> List[Dict[str, Any]]:
    return [_summary(r, now) for r in _runs(events)]


def _summary(run: List[Dict[str, Any]], now: Optional[float] = None) -> Dict[str, Any]:
    now = time.time() if now is None else now
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
        "main_name": out_ref[0]["name"] if out_ref else None,
    }


# limpet load: cargo C = limpets L + ore T, and the sessions say L = r * T
# limpets per refined tonne. Best split L = r C / (1 + r), plus a reserve -
# running out of limpets with room left costs a trip, a few spare cost
# a few tonnes.
DEFAULT_RATIO = 0.4          # laser mining, until your own sessions say better
LIMPET_RESERVE = 0.10
MIN_TONNES = 20              # sessions shorter than this tell nothing


def limpet_load(cargo: int, ratio: float, reserve: float = LIMPET_RESERVE) -> Dict[str, int]:
    if not cargo:
        return {"limpets": 0, "ore": 0}
    n = int(math.ceil(ratio * cargo / (1.0 + ratio) * (1.0 + reserve)))
    n = max(0, min(cargo, n))
    return {"limpets": n, "ore": cargo - n}


def limpet_ratio(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Limpets launched per refined tonne over your sessions, overall and
    per hull type, with what it rests on."""
    use = [r for r in runs if r["total"] >= MIN_TONNES and (r["drones"]["prospector"] + r["drones"]["collection"])]
    def agg(lst):
        lim = sum(r["drones"]["prospector"] + r["drones"]["collection"] for r in lst)
        t = sum(r["total"] for r in lst)
        rocks = sum(r["asteroids"] for r in lst)
        return {"ratio": round(lim / t, 3) if t else None, "sessions": len(lst), "tonnes": t, "limpets": lim,
                "per_rock_prospector": round(sum(r["drones"]["prospector"] for r in lst) / rocks, 2) if rocks else None,
                "per_rock_collector": round(sum(r["drones"]["collection"] for r in lst) / rocks, 2) if rocks else None,
                "tonnes_per_rock": round(t / rocks, 1) if rocks else None}
    out = {"all": agg(use) if use else None, "by_type": {}}
    for typ in sorted({r.get("ship_type") for r in use if r.get("ship_type")}):
        out["by_type"][typ] = agg([r for r in use if r.get("ship_type") == typ])
    return out


def _ly(a, b) -> Optional[float]:
    if not a or not b or None in a or None in b:
        return None
    return math.dist(a, b)


def hotspots_near(db: Any, pos, limit: int = 60) -> List[Dict[str, Any]]:
    """Ring hotspots from the plugin database, nearest first."""
    if db is None:
        return []
    rows = db.query("SELECT h.material, h.label, h.count, h.body_name, h.ring_class, s.name AS system, "
                    "s.id64, s.x, s.y, s.z FROM hotspots h JOIN systems s ON s.id64 = h.sys_id64")
    out = []
    for r in rows:
        ly = _ly(pos, (r["x"], r["y"], r["z"])) if r["x"] is not None else None
        out.append({"key": type_key(r["material"]), "material": r["label"] or r["material"], "count": r["count"],
                    "ring": r["body_name"], "system": r["system"], "id": r["id64"],
                    "ly": round(ly, 1) if ly is not None else None})
    out.sort(key=lambda h: (h["ly"] is None, h["ly"] or 0, -h["count"]))
    return out[:limit] if limit else out


def build_mining(archive: Any, db: Any, live: Dict[str, Any], journal_dir: Optional[str],
                 now: Optional[float] = None, capi_path: Optional[str] = None) -> Dict[str, Any]:
    from . import fleet as fl
    now = time.time() if now is None else now
    evs = archive.events()
    hist = sessions(evs, now)
    # the ship each session was flown in (last Loadout before it began)
    loads = [(parse_ts(e.get("timestamp")) or 0, e) for e in evs if e["event"] == "Loadout"]
    for s in hist:
        lo = None
        for t, e in loads:
            if t > s["start"]:
                break
            lo = e
        if lo:
            s["ship_type"] = (lo.get("Ship") or "").lower()
            s["ship_name"] = lo.get("ShipName")
    out: Dict[str, Any] = {"generated": now, "session": hist[-1] if hist else None,
                           "sessions": list(reversed(hist[-30:]))}
    # ---------------------------------------------------------- tritium -> carrier
    car = archive.carrier()
    month = now - 30 * 86400
    to_carrier = {"30d": 0, "all": 0}
    deposited = {"30d": 0, "all": 0}
    for e in evs:
        ts = parse_ts(e.get("timestamp")) or 0
        if e["event"] == "CargoTransfer":
            for t in e.get("Transfers") or []:
                if (t.get("Type") or "").lower() == "tritium" and t.get("Direction") == "tocarrier":
                    to_carrier["all"] += t.get("Count") or 0
                    if ts >= month:
                        to_carrier["30d"] += t.get("Count") or 0
        elif e["event"] == "CarrierDepositFuel":
            deposited["all"] += e.get("Amount") or 0
            if ts >= month:
                deposited["30d"] += e.get("Amount") or 0
    trit: Dict[str, Any] = {"to_carrier": to_carrier, "deposited": deposited}
    cargo = {}
    if journal_dir:
        from .shipview import _read_json
        cargo = _read_json(os.path.join(journal_dir, "Cargo.json")) or {}
    inv = cargo.get("Inventory") or [] if cargo.get("Vessel", "Ship") == "Ship" else []
    trit["ship"] = sum(c.get("Count") or 0 for c in inv if (c.get("Name") or "").lower() == "tritium")
    out["limpets"] = sum(c.get("Count") or 0 for c in inv if (c.get("Name") or "").lower() == "drones")
    out["cargo_used"] = sum(c.get("Count") or 0 for c in inv)
    if car:
        tank, load = int(car["fuel"] or 0), car["load"] or 0
        per = fl.tritium_for_jump(fl.CARRIER_MAX_JUMP, load, tank) or 1
        from .shipview import hold_tritium
        hold = hold_tritium(capi_path, now)
        if hold:
            trit["hold"] = hold
            if hold["t"]:
                trit["with_hold"] = fl.carrier_range(tank + hold["t"], max(0, load - hold["t"]))
        trit.update({"tank": tank, "tank_max": fl.CARRIER_TANK, "to_full": max(0, fl.CARRIER_TANK - tank),
                     "per_jump": per, "range": fl.carrier_range(tank, load),
                     "with_ship": fl.carrier_range(min(fl.CARRIER_TANK, tank + trit["ship"]), load)
                     if trit["ship"] else None})
        s = out["session"]
        if s and s["tritium"]:
            trit["mined"] = {"t": s["tritium"], "active": s["active"], "jumps": round(s["tritium"] / per, 1),
                             "ly": round(s["tritium"] / per * fl.CARRIER_MAX_JUMP, 0)}
            s["carrier_jumps"] = trit["mined"]["jumps"]
    out["tritium"] = trit
    # ---------------------------------------------------------- goods: mined, sold, against upkeep
    goods: Dict[str, Dict[str, Any]] = {}
    for e in evs:
        if e["event"] == "MiningRefined":
            k = type_key(e.get("Type"))
            g = goods.setdefault(k, {"key": k, "name": e.get("Type_Localised") or k.capitalize(),
                                     "refined": 0, "refined_30d": 0, "sold": 0, "revenue": 0, "revenue_30d": 0})
            g["refined"] += 1
            if (parse_ts(e.get("timestamp")) or 0) >= month:
                g["refined_30d"] += 1
    own = (car or {}).get("stats", {}).get("CarrierID") if car else None
    for e in evs:
        if e["event"] == "MarketSell" and type_key(e.get("Type")) in goods:
            g = goods[type_key(e.get("Type"))]
            if own and e.get("MarketID") == own:          # into your carrier's hold
                g["to_carrier"] = g.get("to_carrier", 0) + (e.get("Count") or 0)
                if g["key"] == "tritium":
                    to_carrier["all"] += e.get("Count") or 0
                    if (parse_ts(e.get("timestamp")) or 0) >= month:
                        to_carrier["30d"] += e.get("Count") or 0
                continue
            g["sold"] += e.get("Count") or 0
            g["revenue"] += e.get("TotalSale") or 0
            if (parse_ts(e.get("timestamp")) or 0) >= month:
                g["revenue_30d"] += e.get("TotalSale") or 0
    for g in goods.values():
        g["avg_price"] = round(g["revenue"] / g["sold"]) if g["sold"] else None
    out["goods"] = sorted(goods.values(), key=lambda g: (-g["refined"]))
    rev30 = sum(g["revenue_30d"] for g in goods.values())
    from . import capi
    fup = (capi.load(capi_path, now) or {}).get("upkeep") or {}
    upkeep = fup.get("per_week") or ((car or {}).get("upkeep") or {}).get("per_week")
    out["income"] = {"revenue_30d": rev30, "per_week": round(rev30 / 30 * 7),
                     "upkeep_per_week": upkeep,
                     "covers_pct": round(100.0 * (rev30 / 30 * 7) / upkeep) if upkeep else None}
    # ---------------------------------------------------------- where: hotspots near you
    pos = (live.get("system") or {}).get("pos")
    out["hotspots"] = hotspots_near(db, pos)
    out["from"] = (live.get("system") or {}).get("name")
    # ---------------------------------------------------------- mining ships
    ships = []
    for s in archive.fleet()["ships"]:
        r = ((s.get("rating") or {}).get("roles") or {}).get("mining") or 0
        if r >= 3:
            ships.append({"name": s.get("name"), "type": s.get("type_name") or s.get("type"), "ident": s.get("ident"),
                          "type_key": s.get("type"),
                          "cargo": s.get("cargo"), "rating": r, "location": s.get("location"),
                          "current": bool(s.get("current"))})
    ships.sort(key=lambda s: (-s["rating"], -(s["cargo"] or 0)))
    out["ships"] = ships
    # ---------------------------------------------------------- limpet load per mining ship
    rat = limpet_ratio(hist)
    plans = []
    for s in ships:
        typ = (s.get("type_key") or "").lower()
        basis = rat["by_type"].get(typ) or rat["all"]
        r = basis["ratio"] if basis and basis["ratio"] else DEFAULT_RATIO
        p = dict(limpet_load(int(s["cargo"] or 0), r), name=s["name"] or s["type"], cargo=s["cargo"], ratio=r,
                 own=bool(rat["by_type"].get(typ)), current=s["current"])
        if s["current"]:
            p["on_board"] = out["limpets"]
            p["diff"] = p["limpets"] - out["limpets"]
        plans.append(p)
    out["limpet_plan"] = {"ratio": rat, "default": DEFAULT_RATIO, "reserve": LIMPET_RESERVE, "ships": plans}
    return out
