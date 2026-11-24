# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
The in-system route order against the exact optimum (RT2, 5.0.1).

The fixtures are the planet groups (a planet with its moons, as the route
clusters them) of five real systems flown on 20. and 23.11.2026, placed by
sysroute at the time the route was built, in light seconds from the arrival
star - nothing else (no names, no commander data). Up to 5.0.0 the route
was nearest neighbour plus 2-opt with the first stop fixed; in "worst" it
went out to the far planet at 15 800 LS and came back to one at 5 700 LS,
22 % more distance than the best order. Every fixture and a set of random
systems must now come out at the Held-Karp optimum (exact for up to 10
groups), and 40 groups must stay fast.

    python tests/route_order.py      (from the plugin folder)
"""
import itertools
import os
import random
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plugin_pkg  # noqa: E402
plugin_pkg.package()
from SHBOXSEARCH.sysroute import (DEFAULT_MODEL, F_ALL, Body, _dist, _nearest_neighbour,  # noqa: E402
                                  _best_tour, plan_route)

FIXTURES = {
    # 10 groups: 2-opt alone went ... 9, 10, 8 (48 711 LS); best ... 8, 7, 9, 10 (37 858 LS)
    "worst": [[724.7, 129.9, 0.0], [411.3, 161.1, -0.1], [577.2, 1083.0, -0.0], [1561.7, 5526.2, -26.0],
              [-66.8, 144.3, 0.0], [-16.8, -264.5, -0.1], [9104.7, -12895.4, 589.5],
              [435.5, -3396.1, 2.0], [79.4, 54.5, 0.0], [-4716.9, -8173.9, -834.9]],
    # the first stop had to change: 10 942 LS -> 9 203 LS
    "first_moves": [[-483.1, 3437.5, -12.4], [-876.9, 588.2, 3.0], [-883.4, 563.5, 1.1],
                    [918.9, -2470.7, -1.5], [870.7, -1121.6, 0.3], [882.5, -1151.9, 0.3]],
    "six": [[26.2, -989.8, -0.2], [1448.5, 3.4, 0.1], [390.4, 654.1, 0.0], [1445.4, 1175.8, -3.0],
            [1729.3, 1859.1, 0.6], [1537.1, 1194.9, 5.1]],
    "eight": [[-356.9, 334.8, -0.1], [-357.3, 334.8, -0.1], [1781.8, 36.8, -739.5], [1028.2, -1259.4, 0.0],
              [-419.3, -2678.2, -877.2], [-642.1, -291.0, 2.9], [-358.4, -156.8, -2.9],
              [-1432.9, 1717.8, -3077.2]],
    "seven": [[-1340.5, -2029.3, -1.1], [-525.0, -505.7, 0.2], [-517.7, -105.5, -0.2], [-4476.4, 740.3, -30.2],
              [-685.7, 632.8, 0.7], [-829.0, 1115.1, 0.3], [2643.6, 1916.9, -0.7]],
}
START = (0.0, 0.0, 0.0)


def _cost(pts, order, start=START):
    c, p = 0.0, start
    for i in order:
        c += DEFAULT_MODEL.hop(_dist(p, pts[i]))
        p = pts[i]
    return c


def _optimum(pts, start=START):
    """Held-Karp over an open path from start: the exact minimum cost."""
    n = len(pts)
    hop = [[DEFAULT_MODEL.hop(_dist(a, b)) for b in pts] for a in pts]
    dp = {(1 << i, i): DEFAULT_MODEL.hop(_dist(start, pts[i])) for i in range(n)}
    for size in range(2, n + 1):
        for sub in itertools.combinations(range(n), size):
            mask = sum(1 << i for i in sub)
            for j in sub:
                pm = mask ^ (1 << j)
                dp[(mask, j)] = min(dp[(pm, k)] + hop[k][j] for k in sub if k != j)
    return min(dp[((1 << n) - 1, j)] for j in range(n))


def _order(pts):
    return _best_tour(pts, START, DEFAULT_MODEL)


class RouteOrder(unittest.TestCase):

    def test_fixtures_reach_the_optimum(self):
        for name, pts in FIXTURES.items():
            pts = [tuple(p) for p in pts]
            order = _order(pts)
            self.assertEqual(sorted(order), list(range(len(pts))), name)
            self.assertAlmostEqual(_cost(pts, order), _optimum(pts), delta=0.5, msg=name)

    def test_worst_no_longer_returns_from_the_far_planet(self):
        pts = [tuple(p) for p in FIXTURES["worst"]]
        order = _order(pts)
        ls = sum(_dist(a, b) for a, b in zip([START] + [pts[i] for i in order], [pts[i] for i in order]))
        self.assertLess(ls, 38000.0)
        self.assertEqual(order[-1], 6, "the farthest group (15 800 LS) comes last")

    def test_random_systems_within_one_percent(self):
        rnd = random.Random(501)
        worst = 0.0
        for _ in range(60):
            n = rnd.randint(4, 9)
            pts = [(rnd.uniform(-6000, 6000), rnd.uniform(-6000, 6000), rnd.uniform(-300, 300))
                   for _ in range(n)]
            got, best = _cost(pts, _order(pts)), _optimum(pts)
            self.assertGreaterEqual(got, best - 1e-6)
            worst = max(worst, got / best - 1.0)
        self.assertLess(worst, 0.01, "worst random system %.2f %% above the optimum" % (worst * 100))

    def test_never_worse_than_nearest_neighbour(self):
        rnd = random.Random(7)
        for _ in range(40):
            pts = [(rnd.uniform(-9000, 9000), rnd.uniform(-9000, 9000), 0.0) for _ in range(rnd.randint(2, 25))]
            nn = _nearest_neighbour(pts, START)
            self.assertLessEqual(_cost(pts, _order(pts)), _cost(pts, nn) + 1e-6)

    def test_forty_groups_stay_fast(self):
        rnd = random.Random(40)
        pts = [(rnd.uniform(-20000, 20000), rnd.uniform(-20000, 20000), 0.0) for _ in range(40)]
        t = time.perf_counter()
        _order(pts)
        self.assertLess(time.perf_counter() - t, 1.5)

    def test_plan_route_uses_it(self):
        """The whole way: bodies at the fixture places, plan_route orders them."""
        pts = FIXTURES["worst"]
        bodies = {0: Body(0, "T", kind="Star", arrival_ls=0.0)}
        for i, p in enumerate(pts, 1):
            b = Body(i, "T %d" % i, kind="Planet", parent_id=0,
                     arrival_ls=_dist(START, p), rel=tuple(p))
            bodies[i] = b
        route = plan_route("T", bodies, filters=[F_ALL], skip_arrival=True)
        self.assertEqual(len(route.stops), len(pts))
        self.assertLess(route.total_ls, 38000.0)


if __name__ == "__main__":
    unittest.main()
