# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
SHIP > MATERIALS (5.1.0, user 24.11.): everything you have collected, with
the count.

Ship materials (raw, manufactured, encoded): the last ``Materials`` event
(written at every login) and what happened since - collected, discarded,
synthesised, crafted, traded, given away, mission rewards (the same changes
as JUMPONIUM, ``materials._material_changes``); per material also the change
since that login. On-foot goods (items, components, data, consumables): the
game's ``ShipLocker.json`` in the journal folder, read only.
"""
import json
import os
from typing import Any, Dict, List, Optional

from . import materials

CATS = ("Raw", "Manufactured", "Encoded")
# raw materials by grade; the game keeps at most materials.CAP[grade] of each
# and still writes MaterialCollected when one is full (user's journal 24.11.:
# carbon 299 + 3 counted as 302) - extends materials.GRADE (jumponium)
RAW_GRADE = dict({m: 1 for m in ("carbon", "iron", "lead", "nickel", "phosphorus", "rhenium", "sulphur")},
                 **{m: 2 for m in ("arsenic", "chromium", "germanium", "manganese", "vanadium", "zinc", "zirconium")},
                 **{m: 3 for m in ("boron", "cadmium", "mercury", "molybdenum", "niobium", "tin", "tungsten")},
                 **{m: 4 for m in ("antimony", "polonium", "ruthenium", "selenium", "technetium", "tellurium",
                                   "yttrium")})
LOCKER = ("Items", "Components", "Data", "Consumables")


def _name(key: str, loc: Optional[str]) -> str:
    return loc if loc and "$" not in loc else key[:1].upper() + key[1:]


def _learn(e: Dict[str, Any], names: Dict[str, str], cats: Dict[str, str]) -> None:
    """Names and categories the event tells (MaterialCollected, MaterialTrade ...)."""
    parts = [e] + [e.get(k) or {} for k in ("Paid", "Received")]
    for p in parts:
        raw = p.get("Name") or p.get("Material")
        if not raw:
            continue
        k = materials._k(raw)
        loc = p.get("Name_Localised") or p.get("Material_Localised")
        if loc and "$" not in loc:
            names[k] = loc
        if p.get("Category") in CATS:
            cats.setdefault(k, p["Category"])


def ship_materials(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The materials on board: {"base_ts", "rows": [{key, name, cat, count,
    since}]} - ``since`` is the change since the last login's list."""
    evs = [e for e in events if e["event"] in materials.EVENTS]
    base = next((i for i in range(len(evs) - 1, -1, -1) if evs[i]["event"] == "Materials"), None)
    have: Dict[str, int] = {}
    start: Dict[str, int] = {}
    names: Dict[str, str] = {}
    cats: Dict[str, str] = {}
    for e in evs:                          # names and categories from the whole history
        _learn(e, names, cats)
    if base is not None:
        for cat in CATS:
            for m in evs[base].get(cat) or []:
                k = materials._k(m.get("Name"))
                have[k] = start[k] = int(m.get("Count") or 0)
                cats[k] = cat
                if m.get("Name_Localised") and "$" not in m["Name_Localised"]:
                    names[k] = m["Name_Localised"]
    for e in evs[(base + 1) if base is not None else 0:]:
        for raw, n in materials._material_changes(e):
            if not raw:
                continue
            k = materials._k(raw)
            have[k] = max(0, have.get(k, 0) + int(n or 0))
            g = RAW_GRADE.get(k)
            if g:
                have[k] = min(have[k], materials.CAP[g])
    rows = [{"key": k, "name": _name(k, names.get(k)), "cat": cats.get(k, "?"), "count": n,
             "since": n - start.get(k, 0), "grade": RAW_GRADE.get(k),
             "cap": materials.CAP[RAW_GRADE[k]] if k in RAW_GRADE else None}
            for k, n in have.items() if n or start.get(k)]
    rows.sort(key=lambda r: (r["cat"], r["name"].lower()))
    return {"base_ts": evs[base].get("timestamp") if base is not None else None, "rows": rows}


def ship_locker(journal_dir: Optional[str]) -> Optional[Dict[str, Any]]:
    """The on-foot goods from ShipLocker.json: {"ts", "rows": [{name, cat,
    count}]}, or None without the file."""
    if not journal_dir:
        return None
    try:
        with open(os.path.join(journal_dir, "ShipLocker.json"), encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return None
    total: Dict[tuple, int] = {}
    for cat in LOCKER:
        for m in d.get(cat) or []:
            k = (cat, _name(materials._k(m.get("Name")), m.get("Name_Localised")))
            total[k] = total.get(k, 0) + int(m.get("Count") or 0)
    rows = [{"cat": c, "name": n, "count": v} for (c, n), v in total.items() if v]
    rows.sort(key=lambda r: (LOCKER.index(r["cat"]), r["name"].lower()))
    return {"ts": d.get("timestamp"), "rows": rows}


def build_inventory(archive: Any, journal_dir: Optional[str], now: float) -> Dict[str, Any]:
    """MATERIALS: ship materials and the ship locker, with counts."""
    return {"generated": now, "ship": ship_materials(archive.events()), "locker": ship_locker(journal_dir)}
