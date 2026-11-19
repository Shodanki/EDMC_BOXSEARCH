# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
NH1 (5.0, user 19.11.2026): the next hop, one jump at a time.

In some regions the galaxy map wrongly shows the systems as permit-locked,
so the game plots no route there: the commander selects one system after
the other in the map and jumps hop by hop. Hardly anyone flies there, so
the chance of a system nobody has visited is above the average.

This lists the systems within the ship's jump range (Loadout MaxJumpRange)
around the current position that this commander has not visited, from the
plugin database (journals, EDDiscovery, Spansh, EDSM; read only), each with
the chance of a find (FX5 target_odds), its information level (I1: "in no
database" / "not checked" / "in a database") and the distance. The best
come first: the higher chance, then the less known, then the nearer. A
position the plugin only estimated from the name (boxel centre) is marked
approximate. The list is worked out again at every request, so after each
jump it starts from the new position.

Most systems out there are in no database at all, so the list also names
the boxels within reach (mass codes b to e, BOXEL_MCS) whose survey is not
complete: their galaxy map search prefix ("Col 132 Sector AB-C c8-") lists
every system of that boxel in the map, also the ones nobody has visited -
the plugin's probe idea (procgen.boxel_prefix), for the next hop. Per mass
code the nearest boxels without a known system first, then the nearest.
The distance is to the boxel's centre (~, up to half the boxel's size).

The FIS only lists and copies the name for the galaxy map's search: it
sends nothing to the game.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

LIMIT = 10
BOXEL_MCS = (1, 2, 3, 4)          # mass codes b-e: 20, 40, 80, 160 ly boxels
BOXELS_PER_MC = 2
LEVEL_RANK = {"unchecked": 0, "checked": 1, "known": 2, "inhabited": 3}

_SQL = ("SELECT name, id64, x, y, z, quality, sources, star_class, visited FROM systems "
        "WHERE x BETWEEN ? AND ? AND y BETWEEN ? AND ? AND z BETWEEN ? AND ? AND x IS NOT NULL")


def _range(live: Dict[str, Any]) -> float:
    try:
        return max(0.0, float((live.get("ship") or {}).get("max_jump") or 0))
    except (TypeError, ValueError):
        return 0.0


def _near(db: Any, pos: List[float], rng: float) -> List[Dict[str, Any]]:
    """The systems in the cube around pos, one row per system (best position)."""
    x, y, z = pos
    best: Dict[str, Dict[str, Any]] = {}
    raw = [dict(r) for r in db.query(_SQL, (x - rng, x + rng, y - rng, y + rng, z - rng, z + rng))]
    for r in db.with_visits(raw):
        k = str(r.get("name") or "").lower()
        if k and (k not in best or (r.get("quality") or 0) > (best[k].get("quality") or 0)):
            best[k] = r
    return list(best.values())


def build_nexthop(db: Any, live: Dict[str, Any], limit: int = LIMIT) -> Dict[str, Any]:
    """{from, range_ly, rows: [{name, ly, level, approx, odds}], total, why}."""
    from .learn import target_odds
    from .model import Q_ESTIMATE, info_level
    cur = (live or {}).get("system") or {}
    pos, rng = cur.get("pos"), _range(live or {})
    out: Dict[str, Any] = {"from": cur.get("name"), "range_ly": round(rng, 2) or None, "rows": [], "total": 0}
    if not pos or rng <= 0 or db is None or not db.has_table("systems"):
        out["why"] = "no position" if not pos else "no range" if rng <= 0 else "no database"
        return out
    regions = db.shell_regions()
    rows, near = [], _near(db, pos, rng)
    for r in near:
        ly = math.dist(pos, (r["x"], r["y"], r["z"]))
        if ly < 0.05 or ly > rng or r.get("visited") or (cur.get("name") or "").lower() == str(r["name"]).lower():
            continue
        level = info_level(r, regions)[0]
        rows.append({"name": r["name"], "ly": round(ly, 2), "level": level,
                     "approx": (r.get("quality") or 0) <= Q_ESTIMATE,
                     "odds": target_odds(db, r["name"], r.get("star_class"), level, r["y"])})
    rows.sort(key=lambda h: (-((h["odds"] or {}).get("p") or 0), LEVEL_RANK.get(h["level"], 9), h["ly"]))
    out.update(rows=rows[:limit], total=len(rows), boxels=_boxels(db, pos, rng, near))
    return out


def _boxels(db: Any, pos: List[float], rng: float, near: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The boxels within reach whose survey is not complete, with the search
    prefix for the galaxy map (see the module text). Empty without procgen."""
    from .model import plugin
    pg = getattr(plugin(), "procgen", None)
    if pg is None:
        return []
    known: Dict[str, int] = {}
    for r in near:
        pn = pg.parse_name(r.get("name") or "")
        if pn is not None:
            known[pn.boxel_key] = known.get(pn.boxel_key, 0) + 1
    done = {r["key"] for r in db.query("SELECT key FROM boxels WHERE complete=1")} if db.has_table("boxels") else set()
    out: List[Dict[str, Any]] = []
    for mc in BOXEL_MCS:
        cand = []
        for g in pg.boxels_in_sphere(mc, pos, rng):
            ly = math.dist(pos, pg.boxel_center(g, mc))
            labels = pg.boxel_labels(g, mc) if ly <= rng else []
            key = pg.boxel_key_of(labels[0][0], mc, labels[0][1]) if labels else ""
            if key and key not in done:
                cand.append((known.get(key, 0) > 0, ly, key))
        for has, ly, key in sorted(cand)[:BOXELS_PER_MC]:
            out.append({"prefix": pg.boxel_prefix(key), "mc": "abcdefgh"[mc], "ly": round(ly, 1),
                        "half": round(pg.boxel_size(mc) / 2, 1), "known": known.get(key, 0)})
    return out
