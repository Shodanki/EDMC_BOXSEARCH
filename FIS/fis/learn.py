# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
L3/L4: learning from your own data - counting, averages and ranges only.

The knowledge is shared between the commanders on this PC (their journals
and the plugin database), nothing is sent anywhere, nothing is guessed from
outside data:

ring_runs()       every laser-mining run in a ring: which ring (where the
                  prospector reports of the run were taken - SupercruiseExit
                  at a PlanetaryRing names it), the main refined material
                  (= the hotspot you mined), tonnes and hours
ring_rates()      tonnes per hour per ring and material, per ring class and
                  material, per material - average over all runs plus the
                  slowest and fastest run
expected_rate()   what to expect at a hotspot: your runs in that very ring,
                  else in rings of its class, else in any ring - with the
                  level it rests on
rig_rates()       Rhino rigs per planet class: tonnes per rig, rigs per hour
learning_status() L4: how much each part has learnt so far and where it is
                  still thin (STATISTICS)

A rate is only an average of what you did - shown with how many runs it
rests on; a thin one says so.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .live import parse_ts

MIN_RUN_T = 5             # a run below this many tonnes tells nothing about a rate
MIN_RUN_S = 300.0         # ... nor one shorter than five minutes
THIN_RUNS = 3             # fewer runs than this: the rate is marked thin
THIN_RIGS = 5             # fewer rigs than this: thin
THIN_GENUS = 3            # a genus seen on fewer bodies than this: thin
MIN_OUTING_S = 600.0      # rigs per hour only from outings this long or longer
RING_RESET = ("SupercruiseEntry", "FSDJump", "Location", "CarrierJump", "Died", "LoadGame")


def _key(name: Optional[str]) -> str:
    s = (name or "").strip().strip("$;").lower()
    if s.endswith("_name"):
        s = s[:-5]
    return s.replace(" ", "")


# ---------------------------------------------------------------- L3 rings
def ring_runs(events: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Laser-mining runs (mining._runs) with the ring they were flown in."""
    from .mining import _runs
    ring: Optional[str] = None
    tagged: List[Dict[str, Any]] = []
    for e in events:
        ev = e.get("event")
        if ev == "SupercruiseExit":
            ring = e.get("Body") if e.get("BodyType") == "PlanetaryRing" else None
        elif ev in RING_RESET:
            ring = None
        if ring and ev in ("ProspectedAsteroid", "MiningRefined"):
            e = dict(e, _ring=ring)
        tagged.append(e)
    out = []
    for run in _runs(tagged):
        if any(e.get("_vehicle") for e in run):
            continue                                    # ground mining: rig_rates
        count: Dict[str, int] = {}
        for e in run:
            if e.get("_ring"):
                count[e["_ring"]] = count.get(e["_ring"], 0) + 1
        if not count:
            continue
        refined: Dict[str, Dict[str, Any]] = {}
        for e in run:
            if e["event"] == "MiningRefined":
                k = _key(e.get("Type"))
                r = refined.setdefault(k, {"n": 0, "name": e.get("Type_Localised") or k.capitalize()})
                r["n"] += 1
        tonnes = sum(r["n"] for r in refined.values())
        start, end = parse_ts(run[0]["timestamp"]), parse_ts(run[-1]["timestamp"])
        if not refined or start is None or end is None:
            continue
        secs = end - start
        if tonnes < MIN_RUN_T or secs < MIN_RUN_S:
            continue
        main = max(refined, key=lambda k: refined[k]["n"])
        hours = secs / 3600.0
        out.append({"ring": max(count, key=lambda k: count[k]), "mat": main,
                    "mat_name": refined[main]["name"], "t": refined[main]["n"], "all_t": tonnes,
                    "hours": hours, "ts": run[0].get("timestamp")})
    return out


def _agg(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    t = sum(r["t"] for r in runs)
    h = sum(r["hours"] for r in runs)
    each = [r["t"] / r["hours"] for r in runs if r["hours"] > 0]
    rings = {r["ring"] for r in runs}
    return {"runs": len(runs), "tonnes": t, "hours": round(h, 2),
            "t_h": round(t / h, 1) if h else None,
            "lo": round(min(each), 1) if each else None, "hi": round(max(each), 1) if each else None,
            "rings": len(rings), "thin": len(runs) < THIN_RUNS,
            "name": runs[0]["mat_name"] if runs else None}


def ring_rates(runs: List[Dict[str, Any]], ring_class: Dict[str, str]
               ) -> Dict[str, Dict[Tuple[str, str], Dict[str, Any]]]:
    """{'ring': {(ring, mat): agg}, 'class': {(cls, mat): agg}, 'mat': {('*', mat): agg}}."""
    groups: Dict[str, Dict[Tuple[str, str], List[Dict[str, Any]]]] = {"ring": {}, "class": {}, "mat": {}}
    for r in runs:
        cls = ring_class.get(r["ring"]) or "?"
        groups["ring"].setdefault((r["ring"], r["mat"]), []).append(r)
        groups["class"].setdefault((cls, r["mat"]), []).append(r)
        groups["mat"].setdefault(("*", r["mat"]), []).append(r)
    return {lv: {k: _agg(v) for k, v in g.items()} for lv, g in groups.items()}


def expected_rate(rates: Dict[str, Dict[Tuple[str, str], Dict[str, Any]]], ring: str,
                  cls: Optional[str], mat: str) -> Optional[Dict[str, Any]]:
    """Your t/h at a hotspot of `mat` in `ring`: from that ring, else rings of
    its class, else any ring - None when you never mined that material."""
    for level, key in (("ring", (ring, mat)), ("class", (cls or "?", mat)), ("all", ("*", mat))):
        a = (rates.get(level if level != "all" else "mat") or {}).get(key)
        if a and a["t_h"] is not None:
            return dict(a, level=level)
    return None


def ring_classes(db: Any) -> Dict[str, str]:
    """ring name -> ring class (Icy, Rocky, Metal Rich, Metallic) from the
    plugin database: the hotspot list and the rings of scanned bodies."""
    from . import prospect
    from .data import _json
    out: Dict[str, str] = {}
    try:
        for r in db.query("SELECT rings_json FROM bodies WHERE rings_json IS NOT NULL"):
            for g in _json(r["rings_json"], []) or []:
                if g.get("name") and g.get("cls"):
                    out[g["name"]] = prospect.ring_class(g["cls"])
    except Exception:
        pass
    try:
        for h in db.query("SELECT body_name, ring_class FROM hotspots"):
            if h["body_name"] and h["ring_class"] and h["body_name"] not in out:
                out[h["body_name"]] = prospect.ring_class(h["ring_class"])
    except Exception:
        pass
    return out


# ---------------------------------------------------------------- L3 rigs
def _secs(v: Any) -> Optional[float]:
    """A journal time stamp or a number of seconds -> seconds."""
    if isinstance(v, (int, float)):
        return float(v)
    t = parse_ts(str(v)[:19] + "Z") if v else None
    return t


def rig_rates(marks: Iterable[Any], planet_class: Callable[[str], Optional[str]],
              body_state: Callable[[List[Any]], Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Rhino rigs per planet class from the plugin's surface marks (one
    "refined" mark per tonne where a rig was collected; surfacenav groups
    them into rigs per Rhino outing): rigs, tonnes, tonnes per rig, and rigs
    per hour over the outings that lasted MIN_OUTING_S or longer.
    """
    by_body: Dict[str, List[Any]] = {}
    for m in marks:
        b = m["body_name"] if not isinstance(m, dict) else m.get("body_name")
        if b:
            by_body.setdefault(b, []).append(m)
    out: Dict[str, Dict[str, Any]] = {}
    for body, ms in by_body.items():
        rigs = body_state(ms).get("rigs") or []
        if not rigs:
            continue
        cls = planet_class(body) or "?"
        o = out.setdefault(cls, {"rigs": 0, "tonnes": 0, "bodies": set(), "_n": 0, "_h": 0.0})
        o["rigs"] += len(rigs)
        o["tonnes"] += sum(r["tonnes"] for r in rigs)
        o["bodies"].add(body)
        outings: Dict[int, List[Dict[str, Any]]] = {}
        for r in rigs:
            outings.setdefault(r["outing"], []).append(r)
        for lst in outings.values():
            t0 = _secs(lst[0].get("ts"))
            t1 = _secs(lst[-1].get("last_t"))
            if t0 is None or t1 is None:
                continue
            secs = t1 - t0
            if secs >= MIN_OUTING_S:
                o["_n"] += len(lst)
                o["_h"] += secs / 3600.0
    for cls, o in out.items():
        o["bodies"] = len(o["bodies"])
        o["t_per_rig"] = round(o["tonnes"] / o["rigs"], 1) if o["rigs"] else None
        o["rigs_h"] = round(o["_n"] / o["_h"], 1) if o["_h"] else None
        o["thin"] = o["rigs"] < THIN_RIGS
        del o["_n"], o["_h"]
    return out


def rig_rates_db(db: Any) -> Dict[str, Dict[str, Any]]:
    """rig_rates from the plugin database (shared by all commanders)."""
    if db is None or not db.has_table("surface_marks"):
        return {}
    try:
        from .model import plugin
        nav = plugin().surfacenav
    except Exception:
        nav = None
    if nav is None:
        return {}
    bodies = [r["body_name"] for r in db.query(
        "SELECT DISTINCT body_name FROM surface_marks WHERE kind = 'refined'")]
    if not bodies:
        return {}
    marks = [dict(m) for m in db.query(
        "SELECT * FROM surface_marks WHERE body_name IN (%s)" % ",".join("?" * len(bodies)),
        tuple(bodies))]
    cls = {r["name"]: r["planet_class"] for r in db.query(
        "SELECT name, planet_class FROM bodies WHERE name IN (%s)" % ",".join("?" * len(bodies)),
        tuple(bodies))}
    return rig_rates(marks, lambda b: cls.get(b), nav.body_state)


# ---------------------------------------------------------------- shared cache
_CACHE: Dict[str, Any] = {"key": None, "runs": None}


def runs_of(archive: Any) -> List[Dict[str, Any]]:
    """ring_runs over every commander's journals, once per archive change."""
    if archive is None:
        return []
    from .fleet import ALL_COMMANDERS
    key = (id(archive), getattr(archive, "rev", None))
    if _CACHE["key"] != key:
        _CACHE["runs"] = ring_runs(archive.events(ALL_COMMANDERS))
        _CACHE["key"] = key
    return _CACHE["runs"] or []


# ---------------------------------------------------------------- L4
def learning_status(archive: Any, db: Any) -> Dict[str, Any]:
    """
    L4 for STATISTICS: how much each learnt part rests on, and where it is
    still thin - rocks per ring class and hotspot (L1/L2), mining runs per
    ring class and material (L3), rigs per planet class, the bio model.
    """
    from . import prospect
    from .model import _ring_prospects, plugin
    out: Dict[str, Any] = {"min_rocks": prospect.MIN_ROCKS, "thin_runs": THIN_RUNS,
                           "thin_rigs": THIN_RIGS, "thin_genus": THIN_GENUS}
    # rocks per ring class + hotspot
    rocks = []
    try:
        pros = _ring_prospects(archive)
        ring_hs: Dict[str, Tuple[str, List[str]]] = {}
        names = {}
        rc = ring_classes(db)
        for h in db.query("SELECT body_name, material, label, ring_class FROM hotspots"):
            cls0 = prospect.ring_class(h["ring_class"]) or rc.get(h["body_name"], "")
            cls, keys = ring_hs.get(h["body_name"], (cls0, []))
            k = prospect._key(h["material"])
            if k not in keys:
                keys.append(k)
            names[k] = h["label"] or h["material"]
            ring_hs[h["body_name"]] = (cls, keys)
        for ring in pros:
            if ring not in ring_hs and rc.get(ring):
                ring_hs[ring] = (rc[ring], [])
        for (cls, hs), p in prospect.expectations(pros, ring_hs).items():
            if cls == "*" or not cls:
                continue
            rocks.append({"cls": cls, "hotspot": None if hs == "*" else names.get(hs, hs),
                          "rocks": p["rocks"], "rings": len(p["rings"]),
                          "thin": p["rocks"] < prospect.MIN_ROCKS})
    except Exception:
        rocks = []
    rocks.sort(key=lambda r: (r["cls"], r["hotspot"] is not None, -r["rocks"]))
    out["rocks"] = rocks
    # mining runs per ring class + material
    runs = []
    try:
        rates = ring_rates(runs_of(archive), ring_classes(db))
        for (cls, mat), a in rates["class"].items():
            runs.append(dict(a, cls=cls, mat=mat))
    except Exception:
        runs = []
    runs.sort(key=lambda r: (-r["runs"], r["cls"]))
    out["runs"] = runs
    # rigs per planet class
    try:
        rigs = rig_rates_db(db)
    except Exception:
        rigs = {}
    out["rigs"] = sorted((dict(v, cls=k) for k, v in rigs.items()), key=lambda r: -r["rigs"])
    # the bio model (biopredict, from the analysed species in the database)
    bio: Dict[str, Any] = {"bodies": 0, "genera": []}
    try:
        model = plugin().biopredict.BioModel.learn(db.bio_training_rows())
        bio["bodies"] = model.bodies
        bio["genera"] = sorted(({"genus": g.genus, "bodies": g.n, "thin": g.n < THIN_GENUS}
                                for g in model.genera.values()), key=lambda g: -g["bodies"])
    except Exception:
        pass
    out["bio"] = bio
    out["thin"] = {"rocks": sum(1 for r in rocks if r["thin"]), "runs": sum(1 for r in runs if r["thin"]),
                   "rigs": sum(1 for r in out["rigs"] if r["thin"]),
                   "genera": sum(1 for g in bio["genera"] if g["thin"])}
    return out
