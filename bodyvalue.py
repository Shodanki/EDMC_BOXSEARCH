# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
4.12: what the exploration data of a body is worth - an estimate.

The formula the community worked out from the game's payouts (published
on Frontier's forums, used by many tools; written here from the formula,
no code taken): a base value k per star type or planet class (plus a
bonus when terraformable), scaled by the mass to the power 0.2; mapping
multiplies it, with a bonus for an efficient map and for Odyssey; a first
discovery multiplies the whole by 2.6. The game rounds and adds small
things this leaves out - shown as "about" (~).

Plain Python: the plugin's cockpit overlay and the FIS can share it.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

Q = 0.56591828
STAR_K = {"N": 22628, "H": 22628, "SupermassiveBlackHole": 33.5678}
WHITE_DWARF_K = 14057
STAR_K_DEFAULT = 1200
PLANET_K = {
    "Metal rich body": (21790, 0),
    "Ammonia world": (96932, 0),
    "Sudarsky class I gas giant": (1656, 0),
    "Sudarsky class II gas giant": (9654, 0),
    "High metal content body": (9654, 100677),
    "Water world": (64831, 116295),
    "Earthlike body": (64831, 116295),
}
PLANET_K_DEFAULT = (300, 93328)          # rocky, icy and the rest; the bonus when terraformable
ALWAYS_BONUS = ("Earthlike body",)       # earth-likes pay the bonus without a TerraformState
MAP_FIRST_BOTH = 3.699622554
MAP_FIRST_ONLY = 8.0956
MAP_KNOWN = 3.3333333333
EFFICIENT = 1.25
FIRST_DISCOVERY = 2.6
VALUABLE = ("Earthlike body", "Water world", "Ammonia world")
# a body whose mass is not known (scanned while the plugin was not running):
# a typical mass of its class - the mass counts only to the power 0.2
TYPICAL_MASS_EM = {
    "Sudarsky class I gas giant": 60.0, "Sudarsky class II gas giant": 150.0,
    "Sudarsky class III gas giant": 300.0, "Sudarsky class IV gas giant": 600.0,
    "Sudarsky class V gas giant": 800.0, "Gas giant with water based life": 150.0,
    "Gas giant with ammonia based life": 150.0, "Helium rich gas giant": 300.0,
    "Helium gas giant": 300.0, "Water giant": 30.0,
    "Earthlike body": 1.0, "Water world": 1.0, "Ammonia world": 1.0,
    "High metal content body": 0.3, "Metal rich body": 0.3,
    "Rocky body": 0.05, "Rocky ice body": 0.1, "Icy body": 0.1,
}
TYPICAL_MASS_DEFAULT = 0.1


def star_value(star_type: Optional[str], mass: Optional[float], first: bool = False) -> int:
    """A star's scan value (stars cannot be mapped)."""
    st = star_type or ""
    k = STAR_K.get(st) or (WHITE_DWARF_K if st.startswith("D") else STAR_K_DEFAULT)
    v = k + float(mass or 0.0) * k / 66.25
    return int(round(max(500.0, v) * (FIRST_DISCOVERY if first else 1.0)))


def planet_k(planet_class: Optional[str], terraform: Optional[str]) -> float:
    """k of a planet class, with the terraforming bonus when it applies."""
    k, bonus = PLANET_K.get(planet_class or "", PLANET_K_DEFAULT)
    if planet_class in ALWAYS_BONUS or (terraform or "") in ("Terraformable", "Terraforming", "Terraformed"):
        return float(k + bonus)
    return float(k)


def planet_value(planet_class: Optional[str], terraform: Optional[str], mass: Optional[float],
                 first: bool = False, mapped: bool = False, first_map: bool = False,
                 efficient: bool = True) -> int:
    """A planet's value: scanned only, or scanned and mapped."""
    k = planet_k(planet_class, terraform)
    base = k + k * Q * max(float(mass or 0.0), 0.0) ** 0.2
    v = base
    if mapped:
        mult = MAP_FIRST_BOTH if (first and first_map) else MAP_FIRST_ONLY if first_map else MAP_KNOWN
        v = base * mult
        v += max(v * 0.3, 555.0)                 # Odyssey
        if efficient:
            v *= EFFICIENT
    v = max(500.0, v)
    return int(round(v * (FIRST_DISCOVERY if first else 1.0)))


def _col(r: Any, k: str) -> Any:
    try:
        return r[k]
    except (KeyError, IndexError):
        return None


def body_values(r: Any) -> Dict[str, Any]:
    """For one body row (sysdb bodies): value now (as scanned / mapped so
    far) and value once mapped, first discovery and first map flags."""
    first = _col(r, "was_discovered") == 0
    if _col(r, "kind") == "Star":
        v = star_value(_col(r, "star_type"), _col(r, "stellar_mass"), first)
        return {"now": v, "mapped": v, "first": first, "first_map": False, "mappable": False}
    if _col(r, "kind") != "Planet":
        return {"now": 0, "mapped": 0, "first": False, "first_map": False, "mappable": False}
    first_map = _col(r, "was_mapped") == 0
    pc, tf, m = _col(r, "planet_class"), _col(r, "terraform"), _col(r, "mass_em")
    if m is None:
        m = TYPICAL_MASS_EM.get(pc or "", TYPICAL_MASS_DEFAULT)
    done = bool(_col(r, "mapped"))
    scan = planet_value(pc, tf, m, first)
    full = planet_value(pc, tf, m, first, mapped=True, first_map=first_map)
    return {"now": full if done else scan, "mapped": full, "first": first, "first_map": first_map,
            "mappable": True, "done": done}


def worth_mapping(r: Any, min_cr: int = 300_000) -> bool:
    """A planet whose map adds at least min_cr (or a valuable class, or
    terraformable) and is not mapped yet."""
    if _col(r, "kind") != "Planet" or _col(r, "mapped"):
        return False
    bv = body_values(r)
    return (bv["mapped"] - bv["now"] >= min_cr or _col(r, "planet_class") in VALUABLE
            or (_col(r, "terraform") or "") == "Terraformable")


def system_summary(rows: Iterable[Any], body_count: Optional[int] = None) -> Dict[str, Any]:
    """What the system's scanned bodies are worth: now, the gain from
    mapping the ones worth it, how many are new, the notable classes."""
    now = gain = 0
    scanned = new = first_map = 0
    notable: Dict[str, int] = {}
    to_map = 0
    for r in rows:
        if not _col(r, "scanned") and _col(r, "scanned") is not None:
            continue
        bv = body_values(r)
        if not bv["now"]:
            continue
        scanned += 1
        now += bv["now"]
        new += 1 if bv["first"] else 0
        pc = _col(r, "planet_class")
        if pc in VALUABLE:
            notable[pc] = notable.get(pc, 0) + 1
        if (_col(r, "terraform") or "") == "Terraformable":
            notable["terraformable"] = notable.get("terraformable", 0) + 1
        if worth_mapping(r):
            to_map += 1
            gain += bv["mapped"] - bv["now"]
            first_map += 1 if bv["first_map"] else 0
    return {"scanned": scanned, "body_count": body_count, "new": new, "value": now,
            "to_map": to_map, "map_gain": gain, "first_map": first_map, "notable": notable}
