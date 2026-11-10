# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
M4: data you carry and lose when the ship is destroyed - from the journal.

Exobiology: every ScanOrganic "Analyse" since it was sold. A SellOrganicData
takes the species it lists off the pending list (you can sell a part); a
death (Died) loses everything not sold. The value comes from your own
earlier sales of the same species; the first-logged bonus (4x the value,
as your sales show it) counts when the scan says WasLogged false. Species
you never sold have no known value - they are counted, not priced.

Exploration data: only counted (its value needs a formula - B6): systems
honked with the FSS (FSSDiscoveryScan) and bodies mapped (SAAScanComplete)
since a MultiSellExplorationData / SellExplorationData listed that system.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .live import parse_ts

BONUS_FACTOR = 4                 # first logged: 4x the base value on top (own sales)
WARN_CR = 50_000_000             # from here on the sheet advises to sell
WARN_SYSTEMS = 100


def build_unsold(events: List[Dict[str, Any]], values: Optional[Dict[str, Dict[str, int]]] = None
                 ) -> Dict[str, Any]:
    values = values or {}
    bio: List[Dict[str, Any]] = []
    systems: Dict[str, Dict[str, Any]] = {}       # system name -> honked / mapped bodies
    names: Dict[Any, str] = {}                    # SystemAddress -> name (jumps, honks)
    last_sale: Dict[str, Optional[float]] = {"bio": None, "exploration": None}
    lost: Optional[Dict[str, Any]] = None
    for e in events:
        ev = e.get("event")
        ts = parse_ts(e.get("timestamp"))
        if ev in ("FSDJump", "Location", "CarrierJump") and e.get("SystemAddress") is not None:
            names[e["SystemAddress"]] = e.get("StarSystem")
        elif ev == "ScanOrganic" and e.get("ScanType") == "Analyse":
            sp = e.get("Species_Localised") or e.get("Species") or "?"
            bio.append({"species": sp, "variant": e.get("Variant_Localised") or e.get("Variant"),
                        "first": e.get("WasLogged") is False, "ts": ts,
                        "system": names.get(e.get("SystemAddress"))})
        elif ev == "SellOrganicData":
            for b in e.get("BioData") or []:
                sp = b.get("Species_Localised") or b.get("Species")
                for i, x in enumerate(bio):
                    if x["species"] == sp:
                        del bio[i]
                        break
            last_sale["bio"] = ts
        elif ev == "FSSDiscoveryScan":
            nm = e.get("SystemName") or names.get(e.get("SystemAddress"))
            if e.get("SystemAddress") is not None and nm:
                names[e["SystemAddress"]] = nm
            if nm:
                systems.setdefault(nm, {"bodies": e.get("BodyCount") or 0, "mapped": 0})
        elif ev == "SAAScanComplete":
            nm = names.get(e.get("SystemAddress"))
            if nm:
                systems.setdefault(nm, {"bodies": 0, "mapped": 0})["mapped"] += 1
        elif ev in ("MultiSellExplorationData", "SellExplorationData"):
            sold = [d.get("SystemName") for d in e.get("Discovered") or []] or (e.get("Systems") or [])
            for nm in sold:
                systems.pop(nm, None)
            last_sale["exploration"] = ts
        elif ev == "Died":
            if bio or systems:
                lost = {"ts": ts, "bio": len(bio), "systems": len(systems)}
            bio, systems = [], {}
    priced, unknown = 0, 0
    total = 0
    items = []
    for x in bio:
        v = values.get(x["species"])
        val = None
        if v and v.get("value"):
            val = v["value"] * (1 + BONUS_FACTOR if x["first"] else 1)
            total += val
            priced += 1
        else:
            unknown += 1
        items.append(dict(x, value=val))
    mapped = sum(s["mapped"] for s in systems.values())
    advice = None
    if total >= WARN_CR or len(systems) >= WARN_SYSTEMS:
        advice = "sell"
    return {"bio": {"count": len(bio), "value": total, "priced": priced, "unknown": unknown,
                    "first": sum(1 for x in bio if x["first"]), "items": items[-12:],
                    "since": last_sale["bio"]},
            "exploration": {"systems": len(systems), "mapped": mapped,
                            "bodies": sum(s["bodies"] for s in systems.values()),
                            "since": last_sale["exploration"]},
            "lost_last": lost, "advice": advice,
            "warn_cr": WARN_CR, "warn_systems": WARN_SYSTEMS}
