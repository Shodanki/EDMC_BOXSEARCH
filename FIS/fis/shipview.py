# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
SHIP and CARRIER: what the views show, prepared for a glance.

SHIP is organised the way the people on a fighter's deck look at it:

  annunciator  an aircraft-style warning panel, three levels - WARNING (red,
               act now), CAUTION (amber, needs attention), ADVISORY (cyan,
               a state you set: lights, night vision, gear ...). Every lamp
               has a fixed place, dark when off, so a glance shows what changed
  engineer     integrity and on/off of every module by slot group, power draw
               per priority against the power plant, pips, ammunition,
               engineering, a short damage and function report
  logistics    cargo by commodity, capacity, limpets, fuel, ship locker

CARRIER reads like a navy ship's sheet: identity, position and orders,
tritium and range, hold usage, finances, services - and for the CAG the air
wing: every ship in the hangar with its role ratings.

Only what the game's files hold. Module health and ammunition are snapshots
(the game writes them when you dock, outfit or log in), marked with their time.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

from . import fleet as fl
from .live import parse_ts

# Status.json Flags / Flags2 bits used by the panel
F = {"docked": 0, "landed": 1, "gear": 2, "shields": 3, "supercruise": 4, "fa_off": 5,
     "hardpoints": 6, "wing": 7, "lights": 8, "scoop": 9, "silent": 10, "scooping": 11,
     "mass_locked": 16, "fsd_charging": 17, "fsd_cooldown": 18, "low_fuel": 19,
     "overheating": 20, "danger": 22, "interdicted": 23, "in_ship": 24, "in_fighter": 25,
     "in_srv": 26, "analysis": 27, "night_vision": 28}
F2 = {"on_foot": 0, "low_oxygen": 6, "low_health": 7}

RECENT_S = 120          # a heat warning / shutdown counts this long
MODULE_CAUTION = 0.80   # integrity below this: caution
MODULE_WARNING = 0.50
HULL_CAUTION = 0.80
HULL_WARNING = 0.50

# the panel: (key, level) in fixed order - the browser words and places them
PANEL = [
    ("hull_crit", "warning"), ("overheat", "warning"), ("fuel_crit", "warning"),
    ("danger", "warning"), ("interdicted", "warning"), ("canopy", "warning"),
    ("shutdown", "warning"), ("oxygen", "warning"),
    ("shields_down", "caution"), ("hull", "caution"), ("module_dmg", "caution"),
    ("module_off", "caution"), ("ammo", "caution"), ("low_fuel", "caution"),
    ("heat", "caution"), ("silent", "caution"), ("fa_off", "caution"),
    ("lights", "advisory"), ("night_vision", "advisory"), ("gear", "advisory"),
    ("scoop", "advisory"), ("hardpoints", "advisory"), ("supercruise", "advisory"),
    ("scooping", "advisory"), ("fsd_charging", "advisory"), ("fsd_cooldown", "advisory"),
    ("mass_locked", "advisory"), ("analysis", "advisory"), ("docked", "advisory"),
    ("landed", "advisory"),
]


def _bit(v: int, n: int) -> bool:
    return bool((v or 0) >> n & 1)


def _read_json(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _ammo_full(archive: fl.Archive) -> Dict[tuple, int]:
    """Full ammunition per (slot, weapon): the most ever seen in a fitting."""
    full: Dict[tuple, int] = {}
    for e in archive.events():
        if e["event"] != "Loadout":
            continue
        for m in e.get("Modules") or []:
            n = (m.get("AmmoInClip") or 0) + (m.get("AmmoInHopper") or 0)
            if n:
                k = (m.get("Slot"), m.get("Item"))
                full[k] = max(full.get(k, 0), n)
    return full


def build_shipstatus(live: Dict[str, Any], archive: fl.Archive, journal_dir: str, db: Any = None,
                     now: Optional[float] = None) -> Dict[str, Any]:
    now = time.time() if now is None else now
    st = live.get("status") or {}
    flags, flags2 = int(st.get("flags") or 0), int(st.get("flags2") or 0)
    lo = live.get("loadout") or archive.current_loadout()
    ship = live.get("ship") or {}
    alerts = live.get("alerts") or []
    out: Dict[str, Any] = {"generated": now, "status_ts": st.get("ts")}
    if not lo:
        out["empty"] = True
        return out

    names = archive.ship_names(archive.events())
    hull = ship.get("hull") if ship.get("hull") is not None else lo.get("HullHealth")
    out["ship"] = {"type": names.get((lo.get("Ship") or "").lower(),
                                     (lo.get("Ship") or "").replace("_", " ").title()),
                   "name": lo.get("ShipName"), "ident": lo.get("ShipIdent"),
                   "hull": hull, "rebuy": lo.get("Rebuy"),
                   "value": (lo.get("HullValue") or 0) + (lo.get("ModulesValue") or 0),
                   "max_jump": lo.get("MaxJumpRange"), "mass": lo.get("UnladenMass"),
                   "cargo_cap": lo.get("CargoCapacity"), "loadout_ts": parse_ts(lo.get("timestamp"))}

    # ---------------------------------------------------------- modules
    info = _read_json(os.path.join(journal_dir, "ModulesInfo.json")) or {}
    power = {m.get("Slot"): m for m in info.get("Modules") or []}
    ammo_full = _ammo_full(archive)
    groups: Dict[str, List[Dict[str, Any]]] = {"hardpoints": [], "utility": [], "core": [], "optional": []}
    capacity = None
    for m in lo.get("Modules") or []:
        g = fl.slot_group(m.get("Slot"))
        if g == "cosmetic":
            continue
        eng = m.get("Engineering") or {}
        mods = {x.get("Label"): x.get("Value") for x in eng.get("Modifiers") or []}
        if m.get("Slot") == "PowerPlant" and mods.get("PowerCapacity"):
            capacity = float(mods["PowerCapacity"])
        pw = power.get(m.get("Slot")) or {}
        item = {"slot": m.get("Slot"), "size": fl.slot_size(m.get("Slot")),
                "name": fl.module_name(m.get("Item")), "on": m.get("On", True),
                "priority": (pw.get("Priority", m.get("Priority")) or 0) + 1,
                "health": m.get("Health"), "power": pw.get("Power"),
                "eng": ("%s G%s" % (eng.get("BlueprintName", "").split("_")[-1], eng.get("Level"))
                        if eng else None),
                "experimental": eng.get("ExperimentalEffect_Localised") if eng else None}
        if m.get("AmmoInClip") is not None or m.get("AmmoInHopper") is not None:
            n = (m.get("AmmoInClip") or 0) + (m.get("AmmoInHopper") or 0)
            full = ammo_full.get((m.get("Slot"), m.get("Item")))
            item["ammo"] = n
            item["ammo_pct"] = round(100.0 * n / full) if full else None
        groups[g].append(item)
    allm = [x for g in groups.values() for x in g]
    draw = sum(x["power"] or 0.0 for x in allm)
    by_prio = []
    for p in range(1, 6):
        by_prio.append(round(sum(x["power"] or 0.0 for x in allm if x["priority"] <= p), 2))
    out["modules"] = groups
    pips = st.get("pips") or [None, None, None]
    out["power"] = {"draw": round(draw, 2), "capacity": capacity,
                    "load_pct": round(100.0 * draw / capacity) if capacity else None,
                    "by_priority": by_prio,
                    "pips": [p / 2.0 if p is not None else None for p in pips],
                    "source_ts": parse_ts(info.get("timestamp"))}

    # ---------------------------------------------------------- report
    damaged = sorted([x for x in allm if x["health"] is not None and x["health"] < MODULE_CAUTION],
                     key=lambda x: x["health"])
    off = [x for x in allm if x["on"] is False]
    empty = [x for x in allm if x.get("ammo") == 0]
    lowammo = [x for x in allm if x.get("ammo_pct") is not None and 0 < x["ammo_pct"] < 25]
    report = []
    for x in damaged:
        report.append({"level": "warning" if x["health"] < MODULE_WARNING else "caution",
                       "key": "module_damaged", "what": x["name"], "value": round(x["health"] * 100)})
    for x in off:
        report.append({"level": "caution", "key": "module_off", "what": x["name"]})
    for x in empty:
        report.append({"level": "caution", "key": "ammo_empty", "what": x["name"]})
    for x in lowammo:
        report.append({"level": "caution", "key": "ammo_low", "what": x["name"], "value": x["ammo_pct"]})
    for a in alerts[-8:]:
        if a.get("event") == "AfmuRepairs":
            report.append({"level": "advisory", "key": "afmu",
                           "what": fl.readable_module(a.get("module"), a.get("module_key")),
                           "value": round((a.get("health") or 0) * 100), "ts": a.get("ts")})
    if capacity and draw > capacity:
        report.append({"level": "caution", "key": "power_over", "value": round(100 * draw / capacity)})
    out["report"] = report
    out["integrity"] = {"min": min((x["health"] for x in allm if x["health"] is not None), default=None),
                        "damaged": len(damaged), "off": len(off), "modules": len(allm)}

    # ---------------------------------------------------------- panel
    def recent(ev: str) -> bool:
        return any(a.get("event") == ev and now - (a.get("ts") or 0) <= RECENT_S for a in alerts)

    in_ship = _bit(flags, F["in_ship"]) or not (_bit(flags, F["in_srv"]) or _bit(flags2, F2["on_foot"]))
    parked = _bit(flags, F["docked"]) or _bit(flags, F["landed"])
    fuel_w = (live.get("fuel_warning") or "")
    lamps = {
        "hull_crit": hull is not None and hull < HULL_WARNING,
        "overheat": _bit(flags, F["overheating"]),
        "fuel_crit": bool(fuel_w) and "critical" in fuel_w.lower(),
        "danger": _bit(flags, F["danger"]),
        "interdicted": _bit(flags, F["interdicted"]),
        "canopy": any(a.get("event") == "CockpitBreached" for a in alerts),
        "shutdown": recent("SystemsShutdown"),
        "oxygen": _bit(flags2, F2["low_oxygen"]),
        "shields_down": bool(st) and in_ship and not parked and not _bit(flags, F["shields"]),
        "hull": hull is not None and HULL_WARNING <= hull < HULL_CAUTION,
        "module_dmg": bool(damaged),
        "module_off": bool(off),
        "ammo": bool(empty or lowammo),
        "low_fuel": _bit(flags, F["low_fuel"]),
        "heat": recent("HeatWarning") or recent("HeatDamage"),
        "silent": _bit(flags, F["silent"]),
        "fa_off": _bit(flags, F["fa_off"]),
    }
    for k in ("lights", "night_vision", "gear", "scoop", "hardpoints", "supercruise", "scooping",
              "fsd_charging", "fsd_cooldown", "mass_locked", "analysis", "docked", "landed"):
        lamps[k] = _bit(flags, F[k])
    panel = [{"key": k, "level": lv, "on": bool(lamps.get(k))} for k, lv in PANEL]
    master = "warning" if any(p["on"] for p in panel if p["level"] == "warning") else (
        "caution" if any(p["on"] for p in panel if p["level"] == "caution") else "normal")
    out["panel"] = panel
    out["master"] = master
    out["live"] = bool(st)

    # ---------------------------------------------------------- logistics
    cargo = _read_json(os.path.join(journal_dir, "Cargo.json")) or {}
    inv = [{"name": c.get("Name_Localised") or (c.get("Name") or "").capitalize(),
            "key": c.get("Name"), "count": c.get("Count") or 0, "stolen": bool(c.get("Stolen")),
            "mission": bool(c.get("MissionID"))}
           for c in cargo.get("Inventory") or [] if cargo.get("Vessel", "Ship") == "Ship"]
    inv.sort(key=lambda c: -c["count"])
    used = sum(c["count"] for c in inv)
    limpets = sum(c["count"] for c in inv if (c["key"] or "").lower() == "drones")
    locker = _read_json(os.path.join(journal_dir, "ShipLocker.json")) or {}
    fuel = live.get("fuel") or {}
    from . import hazards, materials
    out["jumponium"] = materials.build_jumponium(archive, db, (live.get("system") or {}).get("pos"))
    out["hazards"] = hazards.build_hazards(archive, now=now)
    out["logistics"] = {
        "cargo": inv, "used": used, "capacity": lo.get("CargoCapacity"),
        "free": (lo.get("CargoCapacity") or 0) - used if lo.get("CargoCapacity") is not None else None,
        "limpets": limpets, "cargo_ts": parse_ts(cargo.get("timestamp")),
        "fuel": {"main": fuel.get("main"), "reservoir": fuel.get("reservoir"),
                 "capacity": ship.get("fuel_capacity"), "reserve_cap": ship.get("reserve_capacity")},
        "locker": {k: sum(i.get("Count") or 0 for i in locker.get(k) or [])
                   for k in ("Items", "Components", "Consumables", "Data")},
        "balance": st.get("balance"),
    }
    out["target"] = build_target(live, db)
    out["unsold"] = _unsold(archive)
    return out


_UNSOLD_CACHE: Dict[str, Any] = {"key": None, "val": None}


def _unsold(archive: Any) -> Optional[Dict[str, Any]]:
    """M4, worked out again only when the journals changed (the SHIP sheet
    asks about once a second)."""
    from . import unsold
    try:
        archive.refresh()
        key = (id(archive), getattr(archive, "rev", None))
        if key[1] is not None and _UNSOLD_CACHE["key"] == key:
            return _UNSOLD_CACHE["val"]
        val = unsold.build_unsold(archive.events(), archive.organic_values())
        _UNSOLD_CACHE.update(key=key, val=val)
        return val
    except Exception:            # a broken journal line must not cost the sheet
        return None


def build_target(live: Dict[str, Any], db: Any = None) -> Dict[str, Any]:
    """E5: what is selected right now - the destination of Status.json (a
    body, station or signal in this system, or another system), the FSD
    target of the galaxy map and the locked ship (ShipTargeted), read only."""
    st = live.get("status") or {}
    cur = live.get("system") or {}
    dest = st.get("destination") or None
    d_out = None
    if dest and (dest.get("system") or dest.get("name")):
        here = dest.get("system") is not None and dest.get("system") == cur.get("id64")
        d_out = {"name": dest.get("name"), "here": here, "body_id": dest.get("body")}
        if here and dest.get("body") is not None and db is not None:
            try:
                row = db.body(int(cur["id64"]), int(dest["body"]))
            except Exception:
                row = None
            if row is not None:
                d_out["body"] = row["name"]
                d_out["arrival_ls"] = row["arrival_ls"]
        if not here:
            fsd = live.get("target") or {}
            if fsd.get("id64") is not None and fsd.get("id64") == dest.get("system"):
                d_out["system"] = fsd.get("name")
    return {"destination": d_out, "fsd": live.get("target"),
            "ship": live.get("ship_target"), "system": cur.get("name")}


def _ship_tritium(journal_dir: Optional[str]) -> Optional[int]:
    if not journal_dir:
        return None
    cargo = _read_json(os.path.join(journal_dir, "Cargo.json")) or {}
    if cargo.get("Vessel", "Ship") != "Ship":
        return None
    return sum(c.get("Count") or 0 for c in cargo.get("Inventory") or []
               if (c.get("Name") or "").lower() == "tritium")


def _tritium_more(archive: fl.Archive, live: Dict[str, Any], c: Dict[str, Any],
                  journal_dir: Optional[str], now: float, capi_path: Optional[str] = None) -> Dict[str, Any]:
    """B2: what the ship carries and what you mined, in carrier jumps; the
    tritium for the end of the plotted route."""
    from . import galaxy, mining
    tank, load = int(c["fuel"] or 0), c["load"] or 0
    per = fl.tritium_for_jump(fl.CARRIER_MAX_JUMP, load, tank) or 1
    out: Dict[str, Any] = {"to_full": max(0, fl.CARRIER_TANK - tank)}
    hold = hold_tritium(capi_path, now)
    if hold:
        out["hold"] = hold
        if hold["t"]:
            # tritium in the hold weighs already (it is cargo): as fuel it moves
            # from the load into the tank, jump by jump
            out["with_hold"] = fl.carrier_range(tank + hold["t"], max(0, load - hold["t"]))
    ship = _ship_tritium(journal_dir)
    if ship is not None:
        out["ship"] = ship
        if ship:
            out["with_ship"] = fl.carrier_range(min(fl.CARRIER_TANK, tank + ship), load)
    s = mining.session(archive.events(), now)
    if s and s["tritium"]:
        out["mined"] = {"t": s["tritium"], "active": s["active"], "end": s["end"],
                        "jumps": round(s["tritium"] / per, 1),
                        "ly": round(s["tritium"] / per * fl.CARRIER_MAX_JUMP, 0)}
    route = [h for h in live.get("navroute") or [] if h.get("pos")]
    loc = (c.get("location") or {}).get("StarSystem")
    here = galaxy._positions(archive)(loc) if loc else None
    if route and here:
        dest = route[-1]
        ly = sum((a - b) ** 2 for a, b in zip(dest["pos"], here)) ** 0.5
        if ly > 1:
            out["trip"] = dict(fl.carrier_trip(ly, load, tank), to=dest.get("name"))
    return out


def _capi_hold(capi_path: Optional[str], now: float) -> Optional[Dict[str, Any]]:
    from . import capi
    d = capi.load(capi_path, now)
    return {k: d[k] for k in ("saved", "age_s", "hold", "hold_total", "tritium", "fuel")} if d else None


def hold_tritium(capi_path: Optional[str], now: float) -> Optional[Dict[str, Any]]:
    from . import capi
    d = capi.load(capi_path, now)
    return {"t": d["tritium"], "age_s": d["age_s"], "saved": d["saved"]} if d else None


def build_carrier(archive: fl.Archive, live: Dict[str, Any],
                  now: Optional[float] = None, journal_dir: Optional[str] = None,
                  capi_path: Optional[str] = None) -> Dict[str, Any]:
    now = time.time() if now is None else now
    c = archive.carrier()
    fleet = archive.fleet()
    out: Dict[str, Any] = {"generated": now, "fleet": fleet["ships"], "hangar": fleet["hangar"]}
    if not c:
        out["empty"] = True
        return out
    s = c["stats"]
    su = s.get("SpaceUsage") or {}
    fin = s.get("Finance") or {}
    loc = c.get("location") or {}
    rng = fl.carrier_range(c["fuel"] or 0, c["load"] or 0)
    up = c.get("upkeep") or {}
    avail = fin.get("AvailableBalance")
    # Frontier's own figure beats the estimate from the balance history
    from . import capi
    capd = capi.load(capi_path, now)
    fup = (capd or {}).get("upkeep")
    per_week = fup["per_week"] if fup and fup.get("per_week") else up.get("per_week")
    weeks = (avail / per_week) if per_week and avail else None
    out.update({
        "ident": {"name": s.get("Name"), "callsign": s.get("Callsign"), "type": s.get("CarrierType"),
                  "access": s.get("DockingAccess"), "notorious": s.get("AllowNotorious"),
                  "decommission": s.get("PendingDecommission"), "stats_ts": parse_ts(s.get("timestamp"))},
        "position": {"system": loc.get("StarSystem"), "body_id": loc.get("BodyID"),
                     "ts": parse_ts(c.get("arrived") or loc.get("timestamp")), "pending": c.get("pending"),
                     "jumps": list(reversed(c.get("jumps") or []))},
        "tritium": {"tank": c["fuel"], "tank_max": fl.CARRIER_TANK, "load": c["load"],
                    "range": rng, "per_max_jump": rng["per_jump"],
                    "formula": "5 + ly x (load + tritium + %d) / %d" % (fl.TRITIUM_BASE, fl.TRITIUM_DIV),
                    **_tritium_more(archive, live, c, journal_dir, now, capi_path)},
        "space": {"total": su.get("TotalCapacity"), "crew": su.get("Crew"), "cargo": su.get("Cargo"),
                  "reserved": su.get("CargoSpaceReserved"), "ships": su.get("ShipPacks"),
                  "modules": su.get("ModulePacks"), "free": su.get("FreeSpace")},
        "finance": {"balance": fin.get("CarrierBalance"), "reserve": fin.get("ReserveBalance"),
                    "available": avail, "reserve_pct": fin.get("ReservePercent"),
                    "per_week": per_week, "per_week_estimate": up.get("per_week"),
                    "per_week_source": "frontier" if fup and fup.get("per_week") else "estimate",
                    "upkeep": fup, "drift_per_week": up.get("drift_per_week"),
                    "basis_days": up.get("days"), "weeks_left": round(weeks, 1) if weeks else None,
                    "taxes": {k.replace("TaxRate_", ""): v for k, v in fin.items() if k.startswith("TaxRate_")}},
        "capi": _capi_hold(capi_path, now),
        "services": [{"role": x.get("CrewRole"), "active": x.get("Activated"),
                      "enabled": x.get("Enabled"), "crew": x.get("CrewName")}
                     for x in s.get("Crew") or []],
    })
    return out
