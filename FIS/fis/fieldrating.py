# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
MP3 (5.1.0, user 24.11.): the mining fields rated, from the commander's own
laser-mining sessions - per ring and the material mostly refined there (the
one looked for):

- purity: how many of the prospected rocks held that material at all, and
  its mean share in those;
- prospectors per good rock: prospector limpets launched for every rock
  that held at least the commander's typical share of that material (the
  median over all their rocks of it - tritium and platinum differ);
- by-catch: what else was refined there, in tonnes and share.

Rating against the commander's own average for that material: "good" when
a field needs clearly fewer prospectors per good rock (GOOD_RATIO), "poor"
clearly more (POOR_RATIO), else "fair"; a material mined in one field only
is "fair". Only what was mined; nothing is predicted.
"""
from typing import Any, Dict, Iterable, List, Optional

from .live import parse_ts

GOOD_RATIO = 0.8             # prospectors per good rock against the material's average
POOR_RATIO = 1.25
RING_RESET = ("FSDJump", "Location", "Docked", "SupercruiseEntry")


def _key(name: Optional[str]) -> str:
    return (name or "").strip("$;").replace("_name", "").lower()


def _tagged(events: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The events with the ring they happened in (``_ring``), as learn.ring_runs."""
    ring: Optional[str] = None
    out = []
    for e in events:
        ev = e.get("event")
        if ev == "SupercruiseExit":
            ring = e.get("Body") if e.get("BodyType") == "PlanetaryRing" else None
        elif ev in RING_RESET:
            ring = None
        if ring and ev in ("ProspectedAsteroid", "MiningRefined", "LaunchDrone"):
            e = dict(e, _ring=ring)
        out.append(e)
    return out


def _run_field(run: List[Dict[str, Any]], acc: Dict[tuple, Dict[str, Any]]) -> None:
    """Add one run to its field (ring + material mostly refined)."""
    rings: Dict[str, int] = {}
    refined: Dict[str, Dict[str, Any]] = {}
    for e in run:
        if e.get("_ring"):
            rings[e["_ring"]] = rings.get(e["_ring"], 0) + 1
        if e["event"] == "MiningRefined" and not e.get("_vehicle"):
            k = _key(e.get("Type"))
            r = refined.setdefault(k, {"n": 0, "name": e.get("Type_Localised") or k.capitalize()})
            r["n"] += 1
    if not rings or not refined:
        return
    ring = max(rings, key=lambda k: rings[k])
    main = max(refined, key=lambda k: refined[k]["n"])
    f = acc.setdefault((ring, main), {"ring": ring, "mat": main, "mat_name": refined[main]["name"], "sessions": 0,
                                      "rocks": 0, "with_mat": 0, "share_sum": 0.0, "shares": [], "prospectors": 0,
                                      "main_t": 0, "other": {}, "last": 0.0})
    f["sessions"] += 1
    f["last"] = max(f["last"], parse_ts(run[-1].get("timestamp")) or 0.0)
    for k, r in refined.items():
        if k == main:
            f["main_t"] += r["n"]
        else:
            o = f["other"].setdefault(k, {"name": r["name"], "t": 0})
            o["t"] += r["n"]
    for e in run:
        if e["event"] == "LaunchDrone" and (e.get("Type") or "").lower() == "prospector":
            f["prospectors"] += 1
        elif e["event"] == "ProspectedAsteroid":
            f["rocks"] += 1
            share = max((float(m.get("Proportion") or 0) for m in e.get("Materials") or []
                         if _key(m.get("Name")) == main), default=0.0)
            if share > 0:
                f["with_mat"] += 1
                f["share_sum"] += share
                f["shares"].append(share)


def _median(xs: List[float]) -> Optional[float]:
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return None
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0


def _row(f: Dict[str, Any], good_pct: Optional[float]) -> Dict[str, Any]:
    total_t = f["main_t"] + sum(o["t"] for o in f["other"].values())
    good = sum(1 for x in f["shares"] if good_pct is not None and x >= good_pct)
    catch = sorted(f["other"].values(), key=lambda o: -o["t"])
    return {"ring": f["ring"], "mat": f["mat"], "mat_name": f["mat_name"], "sessions": f["sessions"],
            "rocks": f["rocks"], "purity": round(100.0 * f["with_mat"] / f["rocks"]) if f["rocks"] else None,
            "mean_share": round(f["share_sum"] / f["with_mat"], 1) if f["with_mat"] else None,
            "good_pct": round(good_pct, 1) if good_pct is not None else None, "good": good,
            "prospectors": f["prospectors"], "per_good": round(f["prospectors"] / good, 1) if good else None,
            "rating": None, "main_t": f["main_t"], "bycatch_t": total_t - f["main_t"],
            "bycatch_pct": round(100.0 * (total_t - f["main_t"]) / total_t) if total_t else 0,
            "bycatch": [{"name": o["name"], "t": o["t"]} for o in catch[:4]], "last": f["last"] or None}


def _rate(rows: List[Dict[str, Any]]) -> None:
    """Each field against the commander's average for its material."""
    by: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        by.setdefault(r["mat"], []).append(r)
    for rs in by.values():
        pros, good = sum(r["prospectors"] for r in rs), sum(r["good"] for r in rs)
        avg = pros / good if good else None
        for r in rs:
            if not r["rocks"]:
                continue
            if r["per_good"] is None:
                r["rating"] = "poor"
            elif avg is None or len(rs) == 1:
                r["rating"] = "fair"
            else:
                q = r["per_good"] / avg
                r["rating"] = "good" if q <= GOOD_RATIO else "poor" if q >= POOR_RATIO else "fair"
            r["avg_per_good"] = round(avg, 1) if avg else None


def rate_fields(events: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """MP3: one row per mining field (ring + material looked for), the best
    first (fewest prospectors per good rock), the most recent on a tie."""
    from .mining import _runs
    acc: Dict[tuple, Dict[str, Any]] = {}
    for run in _runs(_tagged(events)):
        if any(e.get("_vehicle") for e in run):
            continue                                        # ground mining has no rings
        _run_field(run, acc)
    shares: Dict[str, List[float]] = {}
    for f in acc.values():
        shares.setdefault(f["mat"], []).extend(f["shares"])
    rows = [_row(f, _median(shares[f["mat"]])) for f in acc.values()]
    _rate(rows)
    order = {"good": 0, "fair": 1, "poor": 2, None: 3}
    rows.sort(key=lambda r: (order[r["rating"]], r["per_good"] if r["per_good"] is not None else 1e9,
                             -(r["last"] or 0)))
    return rows
