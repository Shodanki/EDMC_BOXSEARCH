# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
STATISTICS > ENGINEERING (5.1.0, user 25.11.) - from the journals, read only:

- ST11 engineering history: per engineer the crafts, the blueprints and the
  highest grade rolled, the materials it took; the last crafts.
- ST10 materials flow: per material what was collected, where (in the SRV,
  while mining, or by its kind: raw / manufactured / encoded), when last,
  and what went out again (engineering, synthesis, trades, brokers,
  discarded); the collecting pace per hour of play over the last 30 days.
"""
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .live import parse_ts

ACTIVE_GAP_S = 30 * 60
RECENT_S = 30 * 86400
TOP_ENGINEERS = 8
TOP_MATERIALS = 14
LAST_CRAFTS = 6


def blueprint_name(raw: Optional[str]) -> str:
    """'ShieldGenerator_Optimised' -> 'Shield Generator Optimised'."""
    s = (raw or "").replace("_", " ")
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s).strip() or "?"


def _mat(name: Any) -> str:
    return str(name or "").lower()


def engineering(evs: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """ST11: the crafts per engineer, the blueprints and grades, materials used."""
    eng: Dict[str, Dict[str, Any]] = {}
    used: Dict[str, Dict[str, Any]] = {}
    crafts: List[Dict[str, Any]] = []
    for e in evs:
        if e.get("event") != "EngineerCraft":
            continue
        who = e.get("Engineer") or "?"
        bp, level = blueprint_name(e.get("BlueprintName")), int(e.get("Level") or 0)
        g = eng.setdefault(who, {"engineer": who, "crafts": 0, "blueprints": {}, "last": None})
        g["crafts"] += 1
        g["last"] = e.get("timestamp")
        g["blueprints"][bp] = max(g["blueprints"].get(bp, 0), level)
        for i in e.get("Ingredients") or []:
            if isinstance(i, dict):
                name = i.get("Name_Localised") or str(i.get("Name") or "?").capitalize()
                u = used.setdefault(_mat(i.get("Name")), {"name": name, "n": 0})
                u["n"] += int(i.get("Count") or 0)
        crafts.append({"ts": e.get("timestamp"), "engineer": who, "blueprint": bp, "level": level,
                       "effect": e.get("ApplyExperimentalEffect_Localised") or e.get("ApplyExperimentalEffect")})
    rows = sorted(({"engineer": g["engineer"], "crafts": g["crafts"], "last": g["last"],
                    "blueprints": sorted(({"name": k, "grade": v} for k, v in g["blueprints"].items()),
                                         key=lambda b: (-b["grade"], b["name"]))[:4]}
                   for g in eng.values()), key=lambda r: -r["crafts"])
    top = sorted(used.values(), key=lambda u: -u["n"])[:6]
    return {"crafts": len(crafts), "engineers": rows[:TOP_ENGINEERS],
            "materials_used": sum(u["n"] for u in used.values()), "top_used": top,
            "last": list(reversed(crafts[-LAST_CRAFTS:]))}


def _out_of(e: Dict[str, Any]) -> List[Tuple[str, int, str]]:
    """(material, count, why) that left the stores with this event."""
    ev = e.get("event")
    if ev == "EngineerCraft":
        return [(_mat(i.get("Name")), int(i.get("Count") or 0), "engineering")
                for i in e.get("Ingredients") or [] if isinstance(i, dict)]
    if ev in ("Synthesis", "TechnologyBroker"):
        why = "synthesis" if ev == "Synthesis" else "broker"
        return [(_mat(i.get("Name")), int(i.get("Count") or 0), why) for i in e.get("Materials") or []
                if isinstance(i, dict)]
    if ev == "MaterialTrade":
        p = e.get("Paid") or {}
        return [(_mat(p.get("Material")), int(p.get("Quantity") or 0), "trade")]
    if ev == "MaterialDiscarded":
        return [(_mat(e.get("Name")), int(e.get("Count") or 0), "discarded")]
    return []


def _source(e: Dict[str, Any], in_srv: bool, ring: bool) -> str:
    if in_srv:
        return "srv"
    if ring:
        return "mining"
    return str(e.get("Category") or "other").lower()


def _active_hours(stamps: List[float]) -> float:
    s = 0.0
    for a, b in zip(stamps, stamps[1:]):
        if 0 <= b - a <= ACTIVE_GAP_S:
            s += b - a
    return s / 3600.0


def materials(evs: Iterable[Dict[str, Any]], now: Optional[float] = None) -> Dict[str, Any]:
    """ST10: per material collected (where, when last) and used; the pace
    of the last RECENT_S per hour of play."""
    mats: Dict[str, Dict[str, Any]] = {}
    in_srv = ring = False
    stamps: List[float] = []
    recent = 0
    last_ts = None
    for e in evs:
        ev, ts = e.get("event"), parse_ts(e.get("timestamp"))
        if ts is not None:
            last_ts = ts
        in_srv = True if ev == "LaunchSRV" else False if ev in ("DockSRV", "SRVDestroyed") else in_srv
        if ev == "SupercruiseExit":
            ring = e.get("BodyType") == "PlanetaryRing"
        elif ev in ("SupercruiseEntry", "FSDJump", "Docked"):
            ring = False
        if ts is not None:
            stamps.append(ts)
        if ev == "MaterialCollected":
            name = e.get("Name_Localised") or str(e.get("Name") or "?").capitalize()
            m = mats.setdefault(_mat(e.get("Name")), {"name": name, "cat": e.get("Category"), "got": 0, "used": 0,
                                                      "from": {}, "out": {}, "last": None})
            n = int(e.get("Count") or 0)
            m["got"] += n
            m["last"] = e.get("timestamp")
            src = _source(e, in_srv, ring)
            m["from"][src] = m["from"].get(src, 0) + n
            recent += n if ts is not None and ts >= (now or last_ts or ts) - RECENT_S else 0
        for name, n, why in _out_of(e):
            m = mats.get(name)
            if m is not None:
                m["used"] += n
                m["out"][why] = m["out"].get(why, 0) + n
    now = now or last_ts or 0.0
    hours = _active_hours([t for t in stamps if t >= now - RECENT_S])
    rows = sorted(mats.values(), key=lambda m: -m["got"])
    for m in rows:
        m["from"] = max(m["from"], key=m["from"].get) if m["from"] else None
    return {"kinds": len(rows), "collected": sum(m["got"] for m in rows), "used": sum(m["used"] for m in rows),
            "recent": recent, "recent_hours": round(hours, 1),
            "per_hour": round(recent / hours, 1) if hours >= 1 else None, "rows": rows[:TOP_MATERIALS]}


def build(evs: List[Dict[str, Any]], now: Optional[float] = None) -> Dict[str, Any]:
    """ST10 + ST11 for the STATISTICS answer."""
    return {"engineering": engineering(evs), "materials": materials(evs, now)}
