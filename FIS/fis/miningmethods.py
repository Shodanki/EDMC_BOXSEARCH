# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
MP2 (5.1.0): mining methods compared, from the commander's own sessions.

A session counts as core mining when a core was cracked in it
(AsteroidCracked), as ground mining when it was mined from a surface
vehicle (the Rhino), else as laser mining. The tools come from the ship's
Loadout before the session (mining lasers, abrasion blaster, seismic
charges, sub-surface displacement missiles) - the journal does not say
which tool brought which tonne, so the tools are named, not weighed.

Per method: sessions, hours, tonnes per hour, tonnes per prospected rock,
limpets per refined tonne and - where the commander's own sale prices are
known for most of the tonnes - credits per hour. Only what was mined;
nothing is predicted.
"""
from typing import Any, Dict, Iterable, List, Optional

TOOLS = (("hpt_mininglaser", "laser"), ("hpt_mining_abrblstr", "abrasion"),
         ("hpt_mining_seismchrgwarhd", "seismic"), ("hpt_mining_subsurfdispmisle", "subsurface"))
ORDER = ("laser", "core", "ground")
PRICED_SHARE = 0.8          # credits per hour only when prices cover this share of the tonnes


def tools(loadout: Optional[Dict[str, Any]]) -> List[str]:
    """The mining tools a Loadout carries, in a fixed order."""
    items = [(m.get("Item") or "").lower() for m in (loadout or {}).get("Modules") or []]
    return [name for key, name in TOOLS if any(it.startswith(key) for it in items)]


def method(session: Dict[str, Any]) -> str:
    """ground (surface vehicle), core (a core cracked) or laser."""
    if session.get("kind") == "ground":
        return "ground"
    return "core" if session.get("cracked") else "laser"


def _value(session: Dict[str, Any], prices: Dict[str, int]) -> Optional[int]:
    """Credits the session's ore is worth at the commander's own average sale
    price, or None when prices are known for too few of its tonnes."""
    total = session.get("total") or 0
    if not total:
        return None
    priced = [(r["count"], prices[r["key"]]) for r in session.get("refined") or [] if prices.get(r["key"])]
    if sum(n for n, _p in priced) < PRICED_SHARE * total:
        return None
    return int(sum(n * p for n, p in priced) * total / max(1, sum(n for n, _p in priced)))


def compare(hist: Iterable[Dict[str, Any]], goods: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One row per method the commander used, laser - core - ground."""
    prices = {g["key"]: g["avg_price"] for g in goods if g.get("key") and g.get("avg_price")}
    acc: Dict[str, Dict[str, Any]] = {}
    for s in hist:
        if not s.get("total"):
            continue
        m = method(s)
        a = acc.setdefault(m, {"method": m, "sessions": 0, "minutes": 0, "tonnes": 0, "rocks": 0, "limpets": 0,
                               "value": 0, "valued_minutes": 0, "tools": set(), "goods": {}, "last": 0})
        a["sessions"] += 1
        a["minutes"] += s.get("minutes") or 0
        a["tonnes"] += s["total"]
        a["rocks"] += s.get("asteroids") or 0
        a["limpets"] += sum((s.get("drones") or {}).values())
        a["tools"].update(s.get("tools") or [])
        a["last"] = max(a["last"], s.get("end") or 0)
        for r in s.get("refined") or []:
            a["goods"][r["name"]] = a["goods"].get(r["name"], 0) + r["count"]
        v = _value(s, prices)
        if v is not None:
            a["value"] += v
            a["valued_minutes"] += s.get("minutes") or 0
    return [_row(acc[m]) for m in ORDER if m in acc]


def _row(a: Dict[str, Any]) -> Dict[str, Any]:
    hours = a["minutes"] / 60.0
    top = sorted(a["goods"].items(), key=lambda kv: -kv[1])[:3]
    return {"method": a["method"], "sessions": a["sessions"], "hours": round(hours, 1), "tonnes": a["tonnes"],
            "per_hour": round(a["tonnes"] / hours, 1) if hours else None,
            "per_rock": round(a["tonnes"] / a["rocks"], 1) if a["rocks"] else None,
            "limpets_per_t": round(a["limpets"] / a["tonnes"], 2) if a["tonnes"] and a["limpets"] else None,
            "cr_per_hour": round(a["value"] / (a["valued_minutes"] / 60.0)) if a["valued_minutes"] else None,
            "tools": [t for _k, t in TOOLS if t in a["tools"]], "top": [{"name": n, "t": t} for n, t in top],
            "last": a["last"] or None}
