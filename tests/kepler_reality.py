# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
Kepler positions against the game's own figure (K1, 5.0).

Every Scan event says how far the body is from the arrival star
(DistanceFromArrivalLS). That is an independent value of the game: the
position sysroute computes from the orbital elements has to lie that far
from the arrival star, at the time of the scan. The error is measured in
parts of the body's own semi-major axis; the bar is 1 %.

The fixtures (tests/kepler_scans.json) are real Scan and ScanBaryCentre
events of the developer's journals, cut to the orbital fields (no commander
data). They go through sysdb like in the game, so the test covers the whole
way: journal -> database -> bodies_from_rows -> resolve_positions.

Up to 4.12 every orbit was placed in one shared frame, so moons and the
planets of a companion star came out on the wrong side (median 94 % of the
orbit off). Since 5.0 every level is placed in the frame of its parent.

The moons of a few planets keep a fixed offset in that frame (El Tio 4,
Lalande 11206 A 1, Synuefe OW-V c18-2 A 3): known, open (K2), they run as
expected failures.

    python tests/kepler_reality.py      (from the plugin folder)
"""
import json
import math
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import sysdb  # noqa: E402
import sysroute as sr  # noqa: E402

LHS_129 = 670954366377
EL_TIO = 525890193771
LALANDE = 1183297082050
OW_V = 634480595618
BAR = 0.01          # 1 % of the body's own semi-major axis


def _events():
    with open(os.path.join(HERE, "kepler_scans.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _at(rows, t):
    """The rows with every body moved along its orbit to unix time t (also
    backwards: a parent may have been scanned after its moon)."""
    out = []
    for r in rows:
        d = dict(r)
        if d.get("period") and d.get("scan_ts") and d.get("mean_anom") is not None:
            d["mean_anom"] = d["mean_anom"] + 360.0 * (t - d["scan_ts"]) / d["period"]
            d["scan_ts"] = t
        out.append(d)
    return out


class KeplerReality(unittest.TestCase):
    """Computed distance to the arrival star against DistanceFromArrivalLS."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        db = sysdb.SystemDB(os.path.join(cls.tmp.name, "kepler.sqlite"))
        for e in _events():
            db.ingest_journal_event(e)
        cls.rows = {}
        for sa in (LHS_129, EL_TIO, LALANDE, OW_V):
            cls.rows[sa] = [dict(r) for r in db.bodies_for(sa, None)]
        db.close()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def error(self, sa, name):
        """|computed - game| / semi-major axis of the body, at its scan time."""
        rows = self.rows[sa]
        row = next(r for r in rows if r["name"] == name)
        bodies = sr.bodies_from_rows(_at(rows, row["scan_ts"]), now=None)
        sr.resolve_positions(bodies)
        pos = bodies[row["body_id"]].pos
        return abs(math.sqrt(sum(v * v for v in pos)) - row["arrival_ls"]) / (row["sma"] * sr.LS_PER_METRE)

    def check(self, sa, system, names):
        """Every named body within the bar."""
        for n in names:
            with self.subTest(body=n):
                self.assertLess(self.error(sa, system + " " + n), BAR)

    # -- the cases that work since 5.0 --------------------------------------
    def test_moons_lhs_129_6(self):
        """Six moons of one planet of the arrival star."""
        self.check(LHS_129, "LHS 129", ["6 a", "6 b", "6 c", "6 d", "6 e", "6 f"])

    def test_moons_el_tio_3(self):
        """Six moons, one of them inclined by 5 degrees."""
        self.check(EL_TIO, "El Tio", ["3 a", "3 b", "3 c", "3 d", "3 e", "3 f"])

    def test_planets_of_a_companion_star(self):
        """The arrival star and star B orbit barycentre 0; B's planets are 159,000 LS away."""
        self.check(OW_V, "Synuefe OW-V c18-2", ["B 3", "B 4", "B 5", "B 6", "B 7", "B 8"])

    def test_barycentre_pairs(self):
        """Two planets around a common barycentre that orbits the star."""
        self.check(LHS_129, "LHS 129", ["2", "3"])
        self.check(EL_TIO, "El Tio", ["5", "6", "7", "8"])

    def test_stars_around_a_barycentre(self):
        """Lalande 11206 B and C orbit barycentre 2, which orbits barycentre 0 with A."""
        self.check(LALANDE, "Lalande 11206", ["B", "C"])

    def test_planets_of_the_arrival_star(self):
        """Trivially right before and after: the distance to the parent is the SMA."""
        self.check(OW_V, "Synuefe OW-V c18-2", ["A 1", "A 2", "A 3", "A 4"])

    def test_orbit_line_passes_through_the_body(self):
        """The orbit drawn in the FIS is the orbit the body sits on."""
        rows = self.rows[EL_TIO]
        bodies = sr.bodies_from_rows(rows, now=None)
        sr.resolve_positions(bodies)
        for name in ("El Tio 3 b", "El Tio 3 f", "El Tio 5"):
            b = next(x for x in bodies.values() if x.name == name)
            centre = bodies[b.parent_id].pos
            pts = sr.orbit_points(b, centre, 360)
            near = min(math.dist(p, b.pos) for p in pts)
            ring = math.dist(centre, b.pos)
            with self.subTest(body=name):
                self.assertLess(near, ring * 0.02)

    # -- known offset per parent planet (K2, open) --------------------------
    @unittest.expectedFailure
    def test_moons_el_tio_4(self):
        """El Tio 4: about -34 degrees for all its moons."""
        self.check(EL_TIO, "El Tio", ["4 a", "4 b", "4 e", "4 f", "4 g"])

    @unittest.expectedFailure
    def test_moons_lalande_11206_a_1(self):
        """Lalande 11206 A 1: about -50 degrees."""
        self.check(LALANDE, "Lalande 11206", ["A 1 a", "A 1 b"])

    @unittest.expectedFailure
    def test_moons_ow_v_a_3(self):
        """Synuefe OW-V c18-2 A 3 with its moons a-f (A 3 b and A 3 d, 16.11.)."""
        self.check(OW_V, "Synuefe OW-V c18-2", ["A 3 a", "A 3 b", "A 3 c", "A 3 d", "A 3 e", "A 3 f"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
