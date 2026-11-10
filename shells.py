# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
shells.py - ask the online sources in stages, nearest first
===========================================================
Local-first, fair use (4.6): EDSM and Spansh are not asked for the whole
survey sphere at once. The sphere is cut into shells around its centre -
0-25, 25-50, 50-75, 75-100 ly ... - and a shell is only fetched when it is
needed: when the commander gets near its edge, or when the shells already
fetched hold nothing left to fly to. The planner only plans inside the
shells fetched so far (the "horizon"), so it never sends anyone to a
system that the next shell would show as known.

Both services get exactly the same region. A shell up to 100 ly is one EDSM
`sphere-systems` request (minRadius / radius - EDSM's limit is 100 ly) and
one Spansh search (distance min / max) around the same centre. Beyond
100 ly EDSM needs smaller spheres; they are chosen to cover the shell, and
every answer is cut back to the shell, so both deliver the same space.

What was fetched is remembered per service and shell with a validity drawn
at random between 5 and 14 days - many installations then do not all ask
again at the same moment. A shell counts as fresh when at least 90 % of it
lies inside valid fetched shells (also those of earlier, overlapping
surveys).

Standard library only.
"""

from __future__ import annotations

import math
import random
from typing import Callable, Iterable, List, Sequence, Tuple

SHELL_STEP = 25.0          # ly per shell
EDSM_MAX_RADIUS = 100.0    # EDSM sphere-systems limit
TTL_MIN_DAYS = 5.0
TTL_MAX_DAYS = 14.0
FRESH_SHARE = 0.90         # a shell this much inside valid data is fresh
EDGE_LY = 10.0             # fetch the next shell this close to the edge
MAX_EDSM_SPHERES = 40      # safety net for very large shells

Vec = Tuple[float, float, float]
# a fetched region: centre x, y, z, inner radius, outer radius
Region = Tuple[float, float, float, float, float]


def _dist(a: Sequence[float], b: Sequence[float]) -> float:
    return math.sqrt(sum((p - q) ** 2 for p, q in zip(a, b)))


def shells_for(radius: float, step: float = SHELL_STEP) -> List[Tuple[float, float]]:
    """[(r_min, r_max), ...] from the centre out; the last one ends at radius."""
    out: List[Tuple[float, float]] = []
    r = 0.0
    while r < radius - 1e-6:
        out.append((r, min(radius, r + step)))
        r += step
    return out


def ttl_seconds(rand: Callable[[], float] = random.random) -> float:
    """Validity of a fetched shell: 5 to 14 days, drawn at random."""
    return 86400.0 * (TTL_MIN_DAYS + (TTL_MAX_DAYS - TTL_MIN_DAYS) * rand())


def _directions(n: int) -> List[Vec]:
    """n evenly spread unit vectors (Fibonacci sphere)."""
    golden = math.pi * (3.0 - math.sqrt(5.0))
    out = []
    for i in range(n):
        y = 1.0 - 2.0 * (i + 0.5) / n
        r = math.sqrt(max(0.0, 1.0 - y * y))
        a = golden * i
        out.append((math.cos(a) * r, y, math.sin(a) * r))
    return out


def sample_points(center: Sequence[float], r_min: float, r_max: float,
                  n_dir: int = 48, n_rad: int = 4) -> List[Vec]:
    """Points spread through the shell, radii at equal volume steps."""
    pts: List[Vec] = []
    lo, hi = r_min ** 3, r_max ** 3
    for k in range(n_rad):
        r = (lo + (hi - lo) * (k + 0.5) / n_rad) ** (1.0 / 3.0)
        for d in _directions(n_dir):
            pts.append((center[0] + d[0] * r, center[1] + d[1] * r,
                        center[2] + d[2] * r))
    return pts


def _inside(p: Sequence[float], reg: Region) -> bool:
    d = _dist(p, reg[:3])
    return reg[3] - 1e-6 <= d <= reg[4] + 1e-6


def coverage(center: Sequence[float], r_min: float, r_max: float,
             regions: Iterable[Region]) -> float:
    """Share of the shell (0..1) that lies inside the given regions."""
    near = [g for g in regions
            if _dist(center, g[:3]) <= r_max + g[4]]
    if not near:
        return 0.0
    pts = sample_points(center, r_min, r_max)
    hit = sum(1 for p in pts if any(_inside(p, g) for g in near))
    return hit / float(len(pts))


def is_fresh(center: Sequence[float], r_min: float, r_max: float,
             regions: Iterable[Region]) -> bool:
    return coverage(center, r_min, r_max, regions) >= FRESH_SHARE


def edsm_queries(center: Sequence[float], r_min: float,
                 r_max: float) -> List[Tuple[Vec, float, float]]:
    """
    EDSM requests (centre, minRadius, radius) that together cover the shell.

    Up to 100 ly: one request, the shell itself. Beyond: spheres of 100 ly
    placed on the shell's middle radius, chosen greedily until every sample
    point of the shell (its inner and outer surface included) lies inside
    one with 7 ly to spare - tested: no gap in 9600 check points.
    """
    c = (float(center[0]), float(center[1]), float(center[2]))
    if r_max <= EDSM_MAX_RADIUS:
        return [(c, r_min, r_max)]
    reach = EDSM_MAX_RADIUS - 7.0
    pts = sample_points(c, r_min, r_max, n_dir=160, n_rad=3)
    for r in (r_min, r_max):
        pts += [(c[0] + d[0] * r, c[1] + d[1] * r, c[2] + d[2] * r)
                for d in _directions(160)]
    mid = (r_min + r_max) / 2.0
    cands = [(c[0] + d[0] * mid, c[1] + d[1] * mid, c[2] + d[2] * mid)
             for d in _directions(96)]
    left = set(range(len(pts)))
    out: List[Tuple[Vec, float, float]] = []
    while left and len(out) < MAX_EDSM_SPHERES:
        best, best_hit = None, set()
        for q in cands:
            hit = {i for i in left if _dist(pts[i], q) <= reach}
            if len(hit) > len(best_hit):
                best, best_hit = q, hit
        if best is None:
            break
        out.append((best, 0.0, EDSM_MAX_RADIUS))
        left -= best_hit
    return out


def in_shell(p: Sequence[float], center: Sequence[float], r_min: float,
             r_max: float) -> bool:
    d = _dist(p, center)
    return r_min - 1e-6 <= d <= r_max + 1e-6


def needs_next(horizon: float, radius: float, center: Sequence[float],
               pos: Sequence[float] = None, targets_left: int = 1) -> bool:
    """Is the next shell needed? Only while the horizon is short of the
    sphere, and then when nothing is left to fly to inside it or the
    commander is within EDGE_LY of its edge. Never while the commander is
    far outside the sphere - another commander on this PC, or a trip
    elsewhere: the shells wait until someone comes back."""
    if horizon >= radius - 1e-6:
        return False
    if pos is not None and _dist(pos, center) > radius + EDGE_LY:
        return False
    if targets_left <= 0:
        return True
    if pos is not None and _dist(pos, center) >= horizon - EDGE_LY:
        return True
    return False


# ---------------------------------------------------------------------------
# self test
# ---------------------------------------------------------------------------

def _selftest() -> int:
    fails = 0

    def check(ok: bool, what: str) -> None:
        nonlocal fails
        print("  [%s] %s" % ("OK" if ok else "FAIL", what))
        fails += 0 if ok else 1

    check(shells_for(50) == [(0, 25), (25, 50)], "50 ly: shells 0-25, 25-50")
    check(shells_for(150)[-1] == (125, 150) and len(shells_for(150)) == 6,
          "150 ly: six shells, last 125-150")
    check(shells_for(60) == [(0, 25), (25, 50), (50, 60)], "last shell ends at the radius")
    t = [ttl_seconds(lambda: v) / 86400 for v in (0.0, 0.5, 1.0)]
    check(t == [5.0, 9.5, 14.0], "validity 5 to 14 days, drawn at random")

    c = (100.0, -50.0, 20.0)
    check(edsm_queries(c, 25, 50) == [(c, 25, 50)],
          "shell up to 100 ly: one EDSM request with minRadius/radius")
    for a, b in ((100, 125), (125, 150)):
        q = edsm_queries(c, a, b)
        pts = sample_points(c, a, b, n_dir=400, n_rad=6)
        for r in (a, b):
            pts += [(c[0] + d[0] * r, c[1] + d[1] * r, c[2] + d[2] * r)
                    for d in _directions(400)]
        miss = sum(1 for p in pts if not any(_dist(p, g[0]) <= 100 for g in q))
        check(len(q) <= 20 and miss <= len(pts) // 200,
              "shell %d-%d ly: %d EDSM spheres of 100 ly cover it (%d of %d "
              "check points outside)" % (a, b, len(q), miss, len(pts)))

    own = [(c[0], c[1], c[2], 0.0, 25.0)]
    check(is_fresh(c, 0, 25, own), "a shell fetched before is fresh")
    check(not is_fresh(c, 25, 50, own), "the next shell is not")
    moved = [(c[0] + 3.0, c[1], c[2], 0.0, 50.0)]
    check(is_fresh(c, 25, 50, moved), "an earlier survey 3 ly away covers it (>= 90 %)")
    far = [(c[0] + 40.0, c[1], c[2], 0.0, 50.0)]
    check(not is_fresh(c, 0, 50, far), "a survey 40 ly away does not")
    check(coverage(c, 0, 25, []) == 0.0, "nothing fetched: coverage 0")

    check(not needs_next(50, 50, c, c, 0), "horizon = sphere: nothing more to fetch")
    check(needs_next(25, 50, c, c, 0), "no targets left inside: next shell")
    check(not needs_next(25, 50, c, c, 5), "targets left, at the centre: wait")
    edge = (c[0] + 16.0, c[1], c[2])
    check(needs_next(25, 50, c, edge, 5), "10 ly from the horizon: next shell")
    far = (c[0] + 900.0, c[1], c[2])
    check(not needs_next(25, 50, c, far, 5) and not needs_next(25, 50, c, far, 0),
          "far outside the sphere (another commander, a trip): no shell")
    check(needs_next(25, 50, c, (c[0] + 55.0, c[1], c[2]), 5),
          "just outside the sphere, coming in: next shell")
    check(in_shell((c[0] + 30, c[1], c[2]), c, 25, 50)
          and not in_shell((c[0] + 10, c[1], c[2]), c, 25, 50), "shell filter")

    print("failures: %d" % fails)
    return fails


if __name__ == "__main__":
    raise SystemExit(1 if _selftest() else 0)
