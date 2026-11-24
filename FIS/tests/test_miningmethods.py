# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""MP2 (5.1.0): the mining methods compared, from the commander's own sessions."""

import os
import unittest

from fis import miningmethods as mm


def session(total, minutes, cracked=0, kind="space", rocks=10, limpets=50, refined=None, tools=("laser",), end=100.0):
    return {"total": total, "minutes": minutes, "cracked": cracked, "kind": kind, "asteroids": rocks,
            "drones": {"prospector": limpets // 3, "collection": limpets - limpets // 3}, "tools": list(tools),
            "refined": refined or [{"key": "platinum", "name": "Platinum", "count": total}], "end": end}


class MiningMethodsTest(unittest.TestCase):
    def test_tools_from_the_loadout(self):
        lo = {"Modules": [{"Item": "Hpt_MiningLaser_Fixed_Medium"}, {"Item": "hpt_mining_seismchrgwarhd_turret_medium"},
                          {"Item": "int_refinery_size4_class5"}]}
        self.assertEqual(mm.tools(lo), ["laser", "seismic"])
        self.assertEqual(mm.tools(None), [])

    def test_method_of_a_session(self):
        self.assertEqual(mm.method(session(100, 60)), "laser")
        self.assertEqual(mm.method(session(100, 60, cracked=2)), "core")
        self.assertEqual(mm.method(session(100, 60, cracked=2, kind="ground")), "ground")

    def test_compare(self):
        goods = [{"key": "platinum", "avg_price": 200_000}, {"key": "painite", "avg_price": None}]
        hist = [session(240, 60, end=10.0), session(120, 60, end=20.0, tools=("laser", "abrasion")),
                session(200, 60, cracked=3, rocks=20, tools=("laser", "seismic")),
                session(100, 30, refined=[{"key": "painite", "name": "Painite", "count": 100}]),   # no price
                session(0, 10)]                                                                     # nothing mined
        rows = {r["method"]: r for r in mm.compare(hist, goods)}
        self.assertEqual(list(rows), ["laser", "core"], "laser first, empty sessions left out")
        lz = rows["laser"]
        self.assertEqual((lz["sessions"], lz["hours"], lz["tonnes"]), (3, 2.5, 460))
        self.assertEqual(lz["per_hour"], 184.0)
        self.assertEqual(lz["tools"], ["laser", "abrasion"])
        self.assertEqual(lz["cr_per_hour"], round((240 + 120) * 200_000 / 2.0), "only the priced sessions' time")
        self.assertEqual(lz["top"][0], {"name": "Platinum", "t": 360})
        self.assertEqual(lz["last"], 100.0)                     # the painite session ended last
        core = rows["core"]
        self.assertEqual((core["per_rock"], core["limpets_per_t"], core["tools"]), (10.0, 0.25, ["laser", "seismic"]))
        self.assertIsNone(mm.compare([session(100, 60, refined=[{"key": "x", "name": "X", "count": 100}])], [])[0]
                          ["cr_per_hour"], "no price known: no credits per hour")

    def test_shown_under_history(self):
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "js", "views",
                               "mining.js"), encoding="utf-8") as fh:
            js = fh.read()
        self.assertIn('el("div", { class: "mine-col" }, methods(), goods())', js)
        self.assertIn("function methods()", js)


if __name__ == "__main__":
    unittest.main()
