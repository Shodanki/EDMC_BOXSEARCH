# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""F1: along a plotted route, where to scoop at the latest - and stretches
without a scoopable star that no tank can bridge."""

import unittest

from fis.config import Config

from tests import fixtures as fx

A, P = 0.002, 2.75                     # fuel = A * ly ** P  (10 t at ~22 ly)


def burn(ly):
    return A * ly ** P


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cfg = Config()
        cfg.plugin_dir = fx.PLUGIN_DIR
        cfg.use_plugin_path()
        import deepspace
        from fis import model
        cls.ds, cls.model = deepspace, model

    def fs(self, level, cap=32.0):
        return self.ds.FuelState(capacity=cap, level=level, max_jump=30.0,
                                 jumps=[(d, burn(d)) for d in (10, 15, 20, 25, 30)])


class TestScoopPlan(_Base):
    def test_enough_fuel(self):
        plan = self.ds.scoop_plan(self.fs(30.0), [("B", "M", 10.0), ("C", "L", 10.0)])
        self.assertTrue(plan["ok"])
        self.assertEqual(plan["latest"], [])
        self.assertAlmostEqual(plan["arrive"], 30.0 - 2 * burn(10.0), places=0)

    def test_latest_scoop_is_the_last_star_before_running_low(self):
        # 20 ly ~ 7.6 t per jump; 20 t now, reserve 4.8 t: two jumps fine,
        # the third would cut into the reserve -> scoop at the last KGBFOAM
        # star passed (jump 1: K), not at the brown dwarf of jump 2
        hops = [("B", "K", 20.0), ("C", "L", 20.0), ("D", "T", 20.0), ("E", "G", 20.0)]
        plan = self.ds.scoop_plan(self.fs(20.0), hops, here=("A", "M"))
        self.assertEqual([m["n"] for m in plan["latest"]], [1])
        self.assertEqual(plan["latest"][0]["name"], "B")
        self.assertIsNone(plan["stranded"])
        self.assertEqual(plan["gaps"], [])

    def test_here_counts_as_a_refuel_point(self):
        hops = [("B", "L", 20.0), ("C", "T", 20.0), ("D", "Y", 20.0)]
        plan = self.ds.scoop_plan(self.fs(10.0), hops, here=("A", "G"))
        self.assertEqual(plan["latest"][0]["n"], 0)

    def test_gap_longer_than_the_tank(self):
        hops = [("B", "K", 25.0)] + [("X%d" % i, "L", 25.0) for i in range(4)] + [("Z", "F", 25.0)]
        plan = self.ds.scoop_plan(self.fs(30.0), hops)
        self.assertEqual(len(plan["gaps"]), 1)
        self.assertEqual((plan["gaps"][0]["from"], plan["gaps"][0]["to"]), (2, 6))
        self.assertGreater(plan["gaps"][0]["need"], 32.0)
        self.assertEqual(plan["stranded"]["n"], 3)      # 14 t a jump, 4.8 t reserve
        line = self.ds.scoop_line(plan)
        self.assertEqual(line[1], "alert")

    def test_no_model_no_plan(self):
        fs = self.ds.FuelState(capacity=32.0, level=20.0)
        self.assertIsNone(self.ds.scoop_plan(fs, [("B", "K", 20.0), ("C", "K", 20.0)]))

    def test_line_texts(self):
        plan = self.ds.scoop_plan(self.fs(20.0), [("B", "K", 20.0), ("C", "L", 20.0),
                                                  ("D", "T", 20.0), ("E", "G", 20.0)])
        self.assertEqual(self.ds.scoop_line(plan), ("SCOOP at the latest jump 1/4 K", "warn"))


class TestBriefingMarks(_Base):
    def live(self, level):
        route = [{"name": "A", "id64": 1, "pos": [0, 0, 0], "star_class": "M"}]
        for i, cls in enumerate("KLTG", 1):
            route.append({"name": "H%d" % i, "id64": 1 + i, "pos": [20.0 * i, 0, 0], "star_class": cls})
        return {"navroute": route, "system": {"name": "A", "id64": 1, "pos": [0, 0, 0]},
                "ship": {"fuel_capacity": 32.0, "max_jump": 30.0}, "fuel": {"main": level},
                "jumps": [[d, burn(d)] for d in (10, 15, 20, 25, 30)]}

    def test_navpoint_marked(self):
        fr = self.model.fuel_route(self.live(20.0))
        self.assertEqual([m["idx"] for m in fr["latest"]], [1])          # route index of H1
        from fis.data import Database
        b = self.model.build_briefing(Database(""), self.live(20.0))
        marked = [p["name"] for p in b["navroute"] if p.get("scoop_latest")]
        self.assertEqual(marked, ["H1"])
        self.assertTrue(b["fuel_route"]["latest"])

    def test_single_jump_has_no_plan(self):
        lv = self.live(20.0)
        lv["navroute"] = lv["navroute"][:2]
        self.assertIsNone(self.model.fuel_route(lv))


if __name__ == "__main__":
    unittest.main()
