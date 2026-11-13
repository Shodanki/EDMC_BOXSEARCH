# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
V1c: synthesis for the surface vehicle - the recipes per tier and how many
times each can still be made from the materials on board.

The recipes are learnt from the commander's OWN journal: every Synthesis
event names the recipe ("Fuel Basic", "Ammo Basic", "Repair Standard" -
recorded 12.11.2026 in the Scarab, without "SRV" in the name) and the
materials it used. No table from a wiki is copied; a tier never made yet is
named as not seen. Anything else synthesised while a vehicle was out (the
Rhino's mining rig, for example) is learnt the same way under its own name.

The stock is the one SHIP's JUMPONIUM uses (materials.stock): the last
Materials event with what happened since, here for raw, manufactured and
encoded materials.

Reads the journal only.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import materials

KINDS = ("fuel", "ammo", "repair")             # the vehicle's own recipes
TIERS = ("basic", "standard", "premium")
STARTS = ("LaunchSRV", "LaunchVessel")
ENDS = ("DockSRV", "DockVessel", "SRVDestroyed", "VesselDestroyed", "Died", "LoadGame", "Shutdown")

_cache: Dict[Tuple[int, int, Optional[str]], Dict[str, Any]] = {}


def _k(name: Optional[str]) -> str:
    return (name or "").strip().lower()


def parse_name(name: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """("fuel", "basic") for "Fuel Basic"; (None, None) for anything else."""
    w = _k(name).split()
    if len(w) == 2 and w[0] in KINDS and w[1] in TIERS:
        return w[0], w[1]
    return None, None


def learn(events: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Recipes from Synthesis events: {name_key: {name, kind, tier, materials
    [(key, count)], made, last, vehicles}} - the vehicle's own (Fuel/Ammo/
    Repair <tier>) and anything made while a vehicle was out. The newest
    event of a recipe gives its materials.
    """
    out: Dict[str, Dict[str, Any]] = {}
    out_now: Optional[str] = None
    for e in events:
        ev = e.get("event")
        if ev in STARTS:
            out_now = (e.get("SRVType_Localised") or e.get("VesselType_Localised")
                       or e.get("SRVType") or e.get("VesselType") or "SRV")
        elif ev in ENDS:
            out_now = None
        elif ev == "Synthesis":
            name = (e.get("Name") or "").strip()
            kind, tier = parse_name(name)
            if not name or (kind is None and out_now is None):
                continue                     # a ship recipe (FSD, limpets ...)
            mats = [(_k(m.get("Name")), int(m.get("Count") or 1))
                    for m in e.get("Materials") or [] if m.get("Name")]
            r = out.setdefault(_k(name), {"name": name, "kind": kind, "tier": tier,
                                          "materials": mats, "made": 0, "last": None,
                                          "vehicles": []})
            r["made"] += 1
            if mats:
                r["materials"] = mats
            r["last"] = e.get("timestamp") or r["last"]
            if out_now and out_now not in r["vehicles"]:
                r["vehicles"].append(out_now)
    return out


def names(events: Iterable[Dict[str, Any]]) -> Dict[str, str]:
    """The game's own material names (Name_Localised), where it wrote one."""
    out: Dict[str, str] = {}
    for e in events:
        ev = e.get("event")
        if ev == "Materials":
            for cat in ("Raw", "Manufactured", "Encoded"):
                for m in e.get(cat) or []:
                    if m.get("Name") and m.get("Name_Localised"):
                        out[_k(m["Name"])] = m["Name_Localised"]
        elif ev in ("MaterialCollected", "MaterialDiscarded") and e.get("Name_Localised"):
            out[_k(e.get("Name"))] = e["Name_Localised"]
    return out


def _title(key: str) -> str:
    return key[:1].upper() + key[1:]


def plan(recipes: Dict[str, Dict[str, Any]], have: Dict[str, int],
         local: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Per recipe: the materials with stock, how often it can be made and
    what limits it; the vehicle's three kinds by tier, tiers not seen named."""
    local = local or {}
    rows: List[Dict[str, Any]] = []
    for r in recipes.values():
        mats = [{"key": k, "name": local.get(k) or _title(k), "need": n, "have": have.get(k, 0)}
                for k, n in r["materials"]]
        can = min((m["have"] // m["need"] for m in mats if m["need"] > 0), default=None)
        limit = (min(mats, key=lambda m: (m["have"] // m["need"], m["key"]))["key"]
                 if mats else None)
        rows.append({"name": r["name"], "kind": r["kind"], "tier": r["tier"], "materials": mats,
                     "can": can, "limit": limit if can is not None and mats else None,
                     "missing": [m["key"] for m in mats if m["have"] < m["need"]],
                     "made": r["made"], "last": r["last"], "vehicles": r["vehicles"]})

    def order(x):
        k = KINDS.index(x["kind"]) if x["kind"] in KINDS else len(KINDS)
        t = TIERS.index(x["tier"]) if x["tier"] in TIERS else 0
        return (k, t, x["name"].lower())

    rows.sort(key=order)
    seen = {(x["kind"], x["tier"]) for x in rows if x["kind"]}
    kinds = [{"kind": k, "seen": [t for t in TIERS if (k, t) in seen],
              "not_seen": [t for t in TIERS if (k, t) not in seen]} for k in KINDS]
    return {"recipes": rows, "kinds": kinds}


def build_synthesis(archive: Any) -> Dict[str, Any]:
    """The VEHICLE tab's SYNTHESIS block, computed once per journal change."""
    try:
        archive.refresh()
    except Exception:
        pass
    fid = None
    try:
        fid = archive.commander()[0]
    except Exception:
        pass
    key = (id(archive), int(getattr(archive, "rev", 0) or 0), fid)
    if key in _cache:
        return _cache[key]
    evs = archive.events()
    st = materials.stock(evs)
    out = plan(learn(evs), st["have"], names(evs))
    out["base_ts"] = st["base_ts"]
    _cache.clear()
    _cache[key] = out
    return out
