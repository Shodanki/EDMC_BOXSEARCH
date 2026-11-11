# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
HAZARD LOG: what went wrong (or nearly) - under attack, interdicted, hull
and heat damage, shields down, cockpit breach, systems shut down, a jet cone
hurting the FSD, death - with time and place, for the current session (since
the last LoadGame) or a longer period.

Repeats within REPEAT_S (heat warnings every few seconds) fold into one line
with a count. Reads the journal only.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .live import parse_ts

REPEAT_S = 90
EVENTS = ("UnderAttack", "Interdicted", "EscapeInterdiction", "HullDamage", "HeatWarning", "HeatDamage",
          "ShieldState", "CockpitBreached", "SystemsShutdown", "Died", "JetConeDamage", "JetConeBoost",
          "FighterDestroyed", "SRVDestroyed")
PLACE = ("FSDJump", "Location", "CarrierJump", "ApproachBody", "LeaveBody", "SupercruiseExit", "Touchdown")
LEVEL = {"Died": "danger", "CockpitBreached": "danger", "HullDamage": "danger", "SystemsShutdown": "danger",
         "Interdicted": "danger", "JetConeDamage": "danger", "SRVDestroyed": "danger", "FighterDestroyed": "danger",
         "UnderAttack": "warn", "HeatDamage": "warn", "ShieldState": "warn", "HeatWarning": "warn",
         "EscapeInterdiction": "info", "JetConeBoost": "info"}


def _entry(e: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    ev = e["event"]
    v: Dict[str, Any] = {}
    if ev == "ShieldState":
        if e.get("ShieldsUp"):
            return None                       # shields back up: no hazard
    elif ev == "HullDamage":
        if e.get("Fighter") and not e.get("PlayerPilot"):
            return None
        v["pct"] = round((e.get("Health") or 0) * 100)
    elif ev == "UnderAttack":
        v["target"] = e.get("Target")
    elif ev in ("Interdicted", "EscapeInterdiction"):
        v["by"] = e.get("Interdictor_Localised") or e.get("Interdictor") or "?"
        v["player"] = bool(e.get("IsPlayer"))
        if ev == "Interdicted":
            v["submitted"] = bool(e.get("Submitted"))
    elif ev == "Died":
        v["by"] = e.get("KillerName_Localised") or e.get("KillerName") or ""
    elif ev == "JetConeDamage":
        v["module"] = e.get("Module_Localised") or e.get("Module")
    elif ev == "JetConeBoost":
        v["boost"] = e.get("BoostValue")
    return {"kind": ev, "level": LEVEL.get(ev, "warn"), "t": parse_ts(e.get("timestamp")), "v": v, "n": 1}


def build_hazards(archive: Any, days: Optional[float] = None, now: Optional[float] = None) -> Dict[str, Any]:
    now = time.time() if now is None else now
    evs = archive.events()
    if days:
        since = now - days * 86400
    else:                                     # this session: since the last LoadGame
        lg = next((e for e in reversed(evs) if e["event"] == "LoadGame"), None)
        since = parse_ts(lg.get("timestamp")) if lg else 0
    system = body = None
    out: List[Dict[str, Any]] = []
    for e in evs:
        ev = e["event"]
        if ev in PLACE or ev == "LoadGame":
            if ev in ("FSDJump", "Location", "CarrierJump") and e.get("StarSystem"):
                system = e["StarSystem"]
                body = e.get("Body") if ev == "Location" and e.get("BodyType") != "Star" else None
            elif ev in ("ApproachBody", "SupercruiseExit", "Touchdown") and e.get("Body"):
                body = e.get("Body")
            elif ev == "LeaveBody":
                body = None
            continue
        if ev not in EVENTS:
            continue
        ts = parse_ts(e.get("timestamp")) or 0
        if ts < since:
            continue
        it = _entry(e)
        if it is None:
            continue
        it["system"], it["body"] = system, body
        last = out[-1] if out else None
        if last and last["kind"] == it["kind"] and ts - last["t_last"] <= REPEAT_S and last["system"] == system:
            last["n"] += 1
            last["t_last"] = ts
            if it["kind"] == "HullDamage":
                last["v"]["pct"] = min(last["v"]["pct"], it["v"]["pct"])
            continue
        it["t_last"] = ts
        out.append(it)
    counts: Dict[str, int] = {}
    for it in out:
        counts[it["level"]] = counts.get(it["level"], 0) + 1
    return {"since": since, "days": days, "items": list(reversed(out[-60:])), "counts": counts}
