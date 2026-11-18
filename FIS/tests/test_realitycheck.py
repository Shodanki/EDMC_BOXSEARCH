# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""V0 reality check: each model's error value from what happened."""
import unittest

from fis import realitycheck as rc


class Fuel:
    """A fuel model that burns 0.01 t per ly x mass/100, learnt or not."""

    def __init__(self, js):
        self.js = js

    def cost_of(self, d, m=None):
        return 0.01 * d * (m or 100.0) / 100.0


class RealityTest(unittest.TestCase):
    def test_fuel_online(self):
        js = [(50.0, 0.5, 100.0)] * 4 + [(50.0, 0.55, 100.0), (40.0, 0.4, 100.0)]
        f = rc.fuel(js, Fuel)
        self.assertEqual(f["n"], 2)                 # only jumps with four before them
        self.assertEqual(f["median_pct"], 9.1)      # 0.5 against 0.55 is 9.1 % off; 0.4 exact
        self.assertIsNone(rc.fuel(js[:4], Fuel))

    def test_kepler_and_finds(self):
        per = {1: {"checked": 10, "ok": 9}, 2: {"checked": 10, "ok": 10}, 3: None}
        k = rc.kepler([1, 2, 3], lambda s: per[s])
        self.assertEqual((k["ok_pct"], k["checked"], k["systems"]), (95.0, 20, 2))
        self.assertIsNone(rc.kepler([1], lambda s: 1 / 0))
        fd = rc.finds({"bands": [{"n": 50, "predicted": 0.03, "rate": 0.05},
                                 {"n": 50, "predicted": 0.19, "rate": 0.18}, {"n": 0}]})
        self.assertEqual((fd["gap_pp"], fd["n"]), (1.5, 100))

    def test_rows(self):
        rows = {r["key"]: r for r in rc.build({
            "kepler": {"ok_pct": 91.7, "checked": 2106, "systems": 202},
            "fuel": {"median_pct": 0.8, "p90_pct": 10.1, "n": 646},
            "route": {"ratio": 2.1, "ratio_n": 12},
            "value": {"factor": 0.91, "lo": 0.75, "hi": 1.29, "n": 12},
            "bio": {"bodies": 104, "recall_top3": 0.76, "top1_right": 0.88}})}
        self.assertTrue(rows["kepler"]["good"] and rows["fuel"]["good"] and rows["value"]["good"])
        self.assertIs(rows["route"]["good"], False)                 # twice the estimate: flagged
        self.assertIsNone(rows["finds"]["value"])
        self.assertIsNone(rows["finds"]["good"])                    # no data: thin, not wrong
        self.assertNotIn("work", rows)
        self.assertIn("76 %", rows["bio"]["value"])


if __name__ == "__main__":
    unittest.main()
