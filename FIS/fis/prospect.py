# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
What the rocks of a ring held - and what to expect at a kind of hotspot.

From your own journals only (read only):

* the ring you mine in: SupercruiseExit at a "PlanetaryRing" names it; it
  ends with SupercruiseEntry or a jump
* every ProspectedAsteroid there: its materials with their share, the
  motherlode material

ring_prospects()  per ring: rocks prospected, motherlodes, and per material
                  how many rocks held it and its mean share
expectations()    per ring class and hotspot material (from the plugin
                  database's hotspots): the materials the rocks of such
                  rings also held - "Icy ring, Tritium hotspot: Bromellite in
                  40 % of the rocks, 12 % on average"

Nothing is guessed from outside data; a ring nobody prospected says so.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

TOP = 6
MIN_ROCKS = 30      # below this a group is "thin" and borrows from the broader one
PRIOR_WEIGHT = 20   # how many rocks the broader group counts for (shrinkage)


def wilson(k: int, n: int, z: float = 1.96) -> Tuple[int, int]:
    """95 % range of a share k of n (Wilson score) in percent - honest for
    small samples: 3 of 4 is 30-95 %, 300 of 400 is 70-79 %."""
    if n <= 0:
        return 0, 100
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5 / d
    return max(0, round(100 * (c - h))), min(100, round(100 * (c + h)))


def _key(name: Optional[str]) -> str:
    s = (name or "").strip().strip("$;").lower()
    if s.endswith("_name"):
        s = s[:-5]
    return s.replace(" ", "")


def ring_class(raw: Optional[str]) -> str:
    """'eRingClass_Icy' / 'Icy' -> 'Icy'; MetalRich, Metalic, Rocky kept."""
    return (raw or "").replace("eRingClass_", "").replace("$", "").replace(";", "")


def ring_prospects(events: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    ring: Optional[str] = None
    for e in events:
        ev = e.get("event")
        if ev == "SupercruiseExit":
            ring = e.get("Body") if e.get("BodyType") == "PlanetaryRing" else None
        elif ev in ("SupercruiseEntry", "FSDJump", "Location", "CarrierJump", "Died", "LoadGame"):
            ring = None
        elif ev == "ProspectedAsteroid" and ring:
            r = out.setdefault(ring, {"rocks": 0, "motherlodes": {}, "mats": {}, "last": None})
            r["rocks"] += 1
            r["last"] = e.get("timestamp") or r["last"]
            ml = e.get("MotherlodeMaterial_Localised") or e.get("MotherlodeMaterial")
            if ml:
                r["motherlodes"][ml] = r["motherlodes"].get(ml, 0) + 1
            for m in e.get("Materials") or []:
                k = _key(m.get("Name"))
                if not k:
                    continue
                d = r["mats"].setdefault(k, {"name": m.get("Name_Localised") or m.get("Name") or k,
                                             "rocks": 0, "sum": 0.0})
                d["rocks"] += 1
                d["sum"] += float(m.get("Proportion") or 0.0)
    return out


def summary(r: Optional[Dict[str, Any]], top: int = TOP) -> Optional[Dict[str, Any]]:
    """A ring's prospecting for the view: the most frequent materials first."""
    if not r or not r.get("rocks"):
        return None
    n = r["rocks"]
    mats = sorted(r["mats"].items(), key=lambda kv: (-kv[1]["rocks"], -kv[1]["sum"]))
    out = []
    for k, d in mats[:top]:
        lo, hi = wilson(d["rocks"], n)
        out.append({"key": k, "name": d["name"], "share": round(100.0 * d["rocks"] / n),
                    "lo": lo, "hi": hi, "avg": round(d["sum"] / d["rocks"], 1)})
    return {"rocks": n, "last": r.get("last"), "thin": n < MIN_ROCKS,
            "motherlodes": sorted(r["motherlodes"].items(), key=lambda kv: -kv[1]),
            "mats": out}


def expectations(prospects: Dict[str, Dict[str, Any]],
                 ring_hotspots: Dict[str, Tuple[str, List[str]]]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """
    (ring class, hotspot material key) -> pooled prospecting of every ring
    of that class with such a hotspot; (class, "*") pools every ring of the
    class and ("*", "*") every ring - the broader groups a thin one leans
    on. `ring_hotspots`: ring name -> (ring class, [hotspot material keys]).
    """
    pool: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for ring, r in prospects.items():
        cls, hs = ring_hotspots.get(ring, ("", []))
        # the broader groups too: every ring of this class, every ring
        for h in list(hs) + ["*", "**"]:
            if h == "**":
                cls_key, h_key = "*", "*"
            else:
                cls_key, h_key = cls, h
            p = pool.setdefault((cls_key, h_key), {"rocks": 0, "rings": set(), "motherlodes": {}, "mats": {}})
            p["rocks"] += r["rocks"]
            p["rings"].add(ring)
            for k, d in r["mats"].items():
                q = p["mats"].setdefault(k, {"name": d["name"], "rocks": 0, "sum": 0.0})
                q["rocks"] += d["rocks"]
                q["sum"] += d["sum"]
            for ml, n in r["motherlodes"].items():
                p["motherlodes"][ml] = p["motherlodes"].get(ml, 0) + n
    return pool


def expected_for(pool: Dict[Tuple[str, str], Dict[str, Any]], cls: str, hotspot: str,
                 skip_ring: Optional[str] = None, top: int = TOP) -> Optional[Dict[str, Any]]:
    """
    What rocks held in rings of this class with this hotspot - learning
    from your own data: while that group is thin (< MIN_ROCKS) its shares
    lean on the broader group (every ring of this class, then every ring)
    as if that one added PRIOR_WEIGHT rocks; the more you prospect, the
    more the specific group speaks for itself. None when only this very
    ring (or nothing) has data.
    """
    p = pool.get((cls, hotspot))
    if not p:
        return None
    rings = set(p["rings"]) - ({skip_ring} if skip_ring else set())
    if not rings:
        return None
    s = summary(p, top)
    if s is None:
        return None
    s["rings"] = len(p["rings"])
    s["level"] = "hotspot"
    if p["rocks"] < MIN_ROCKS:
        for key, level in (((cls, "*"), "class"), (("*", "*"), "all")):
            par = pool.get(key)
            if par and par["rocks"] > p["rocks"]:
                n, m = p["rocks"], PRIOR_WEIGHT
                for mat in s["mats"]:
                    q = par["mats"].get(mat["key"])
                    pp = (q["rocks"] / par["rocks"]) if q else 0.0
                    k = p["mats"][mat["key"]]["rocks"]
                    mat["share"] = round(100.0 * (k + m * pp) / (n + m))
                s["level"] = level
                s["borrowed"] = par["rocks"]
                break
    return s
