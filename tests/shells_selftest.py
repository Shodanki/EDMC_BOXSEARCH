# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
Self test of shells.py (moved from the module in 4.12, N7 - verbatim).

    python tests/shells_selftest.py      (from the plugin folder)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plugin_pkg  # noqa: E402
plugin_pkg.package()
from SHBOXSEARCH.shells import (INHABITED, _directions, _dist, coverage, edsm_queries, in_shell,  # noqa: E402
                                info_level, inhabited_event, is_fresh, needs_next, sample_points,
                                shells_for, ttl_seconds)


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

    # I1 information levels
    reg = {"spansh": [(c[0], c[1], c[2], 0.0, 25.0)],
           "edsm": [(c[0], c[1], c[2], 0.0, 50.0)]}
    p_in, p_mid, p_out = (c[0] + 10, c[1], c[2]), (c[0] + 40, c[1], c[2]), \
        (c[0] + 400, c[1], c[2])
    check(info_level(["journal", "EDSM"], p_out, reg) == ("known", []),
          "I1: a database reports it -> known (even outside the frame)")
    check(info_level(["journal"], p_in, reg) == ("checked", ["Spansh", "EDSM"]),
          "I1: inside both shells, nobody has it -> checked by Spansh + EDSM")
    check(info_level(["journal"], p_mid, reg) == ("checked", ["EDSM"]),
          "I1: inside only the EDSM shell -> checked by EDSM")
    check(info_level(["journal", "navroute"], p_out, reg) == ("unchecked", []),
          "I1: outside every shell -> NOT checked, never 'in no database'")
    check(info_level(["journal"], None, reg)[0] == "unchecked",
          "I1: no reliable position -> not checked")
    check(info_level(["journal", INHABITED], p_out, reg)[0] == "inhabited",
          "I1: inhabited -> known without a request")
    check(info_level([], p_in, {})[0] == "unchecked", "I1: no shells at all -> not checked")
    check(inhabited_event({"event": "FSDJump", "Population": 12000})
          and inhabited_event({"event": "Location", "Population": 0,
                               "Factions": [{"Name": "x"}]})
          and not inhabited_event({"event": "FSDJump", "Population": 0})
          and inhabited_event({"event": "Docked", "StationType": "Coriolis"})
          and not inhabited_event({"event": "Docked", "StationType": "FleetCarrier"}),
          "I1: population/factions/station docking = inhabited, a carrier is not")

    print("failures: %d" % fails)
    return fails


if __name__ == "__main__":
    raise SystemExit(1 if _selftest() else 0)
