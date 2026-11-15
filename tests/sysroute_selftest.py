# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
Self test of sysroute.py (moved from the module in 4.12, N7 - verbatim).

    python tests/sysroute_selftest.py      (from the plugin folder)
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plugin_pkg  # noqa: E402
plugin_pkg.package()
from SHBOXSEARCH.sysroute import (Body, F_ALL, is_arrival_star, map_projection, pace_ratio,  # noqa: E402
                                  plan_route, spread_points, start_at_body)


def _selftest() -> int:
    """python sysroute.py - the arrival star can be left out (R2)."""
    fails = 0

    def check(ok: bool, what: str) -> None:
        nonlocal fails
        print("  [%s] %s" % ("OK" if ok else "FAIL", what))
        fails += 0 if ok else 1

    bodies = {
        0: Body(0, "Sys A", kind="Star", arrival_ls=0.0),
        1: Body(1, "Sys A 1", kind="Planet", arrival_ls=120.0, parent_id=0),
        2: Body(2, "Sys A 2", kind="Planet", arrival_ls=900.0, parent_id=0),
        3: Body(3, "Sys B", kind="Star", arrival_ls=5000.0),
    }
    names = lambda r: [s.body.name for s in r.stops]   # noqa: E731
    full = plan_route("Sys", bodies, filters=[F_ALL])
    check("Sys A" in names(full), "by default the arrival star is a stop")
    short = plan_route("Sys", bodies, filters=[F_ALL], skip_arrival=True)
    check("Sys A" not in names(short) and len(short.stops) == len(full.stops) - 1,
          "skip_arrival: the route starts with the first planned body")
    check(is_arrival_star(bodies[0]) and not is_arrival_star(bodies[3]),
          "only the star at 0 LS counts as the arrival star")
    # R3: start at the carrier's body, the arrival star left out
    at = start_at_body(bodies, 2)
    r3 = plan_route("Sys", bodies, filters=[F_ALL], start=at, skip_arrival=True)
    check(at is not None and names(r3)[0] == "Sys A 2" and r3.stops[0].leg_ls < 1.0
          and "Sys A" not in names(r3), "R3: the route starts at the carrier's body")
    check(start_at_body(bodies, 42) is None, "R3: unknown body -> main star")
    # E17: a cluster of five points on one spot spreads out, lone points stay
    pts = {1: (100.0, 100.0), 2: (100.0, 100.0), 3: (101.0, 100.0), 4: (100.0, 101.0),
           5: (100.5, 100.5), 9: (300.0, 50.0), 0: (200.0, 200.0)}
    out = spread_points(pts, 12.0, fixed=[0])
    near = [(a, b) for a in (1, 2, 3, 4, 5) for b in (1, 2, 3, 4, 5)
            if a < b and math.hypot(out[a][0] - out[b][0], out[a][1] - out[b][1]) < 11.0]
    check(not near, "a cluster on one spot is pulled apart (%s)" % near)
    check(out[9] == (300.0, 50.0) and out[0] == (200.0, 200.0), "lone and fixed points stay")
    check(max(math.hypot(out[k][0] - 100, out[k][1] - 100) for k in (1, 2, 3, 4, 5)) < 40,
          "the cluster stays where it was")
    # R1: today's legs - mapping a few minutes each, one with 13 min of repairs
    legs = [(240, 300), (100, 150), (200, 260), (250, 1030), (60, 90), (300, 330)]
    r = pace_ratio(legs)
    check(r is not None and 1.2 <= r <= 1.5, "median pace ignores the repair leg (%.2f)" % (r or 0))
    check(pace_ratio([(240, 300)]) is None, "one leg is not enough")
    check(pace_ratio([(5, 300), (240, 240), (200, 200)]) == 1.0, "legs under 20 s are left out")
    # H6: the map projection drops the flattest axis and scales the radius by log
    proj, rmax = map_projection([(1000.0, 0.0, 0.5), (0.0, 10.0, -0.5), (-3.0, -4.0, 0.0)],
                                100.0, 100.0, 80.0)
    check(rmax == 1000.0 and proj((1000.0, 0.0, 0.5)) == (180.0, 100.0)
          and proj((0.0, 0.0, 7.0)) == (100.0, 100.0), "map: flattest axis (z) dropped, rmax at the edge")
    x, y = proj((0.0, 10.0, 0.0))
    check(x == 100.0 and 100.0 + 80.0 * 0.3 < y < 100.0 + 80.0 * 0.4,
          "map: 10 LS of 1000 LS sits a third out on the log scale")
    print("failures: %d" % fails)
    return fails


if __name__ == "__main__":
    raise SystemExit(1 if _selftest() else 0)
