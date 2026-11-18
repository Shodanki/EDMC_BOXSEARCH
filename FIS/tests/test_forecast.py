# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""B-24 forecasts: the sphere's rest, jumps until the tank is empty, the
chance of life on a landable planet - each with a range and its n."""
import unittest

from fis import forecast


class FuelStub:
    """deepspace.FuelState's surface as forecast.jumps reads it."""

    def __init__(self, level, cost, spread, n, source="fit"):
        self.level, self.typical_jump = level, 50.0
        self._cost, self._l = cost, {"source": source, "spread_pct": spread, "n": n}

    def cost_of(self, dist):
        return self._cost

    def learned(self):
        return self._l


class ForecastTest(unittest.TestCase):
    def test_quartiles(self):
        q = forecast.quartiles([1, 2, 3, 4, 5])
        self.assertEqual((q["lo"], q["mid"], q["hi"], q["n"]), (2.0, 3.0, 4.0, 5))
        self.assertIsNone(forecast.quartiles([]))

    def test_sphere_rest(self):
        f = forecast.sphere({"known": 110, "visited": 10}, [10, 20, 30, 40, 50], [1e6, 2e6, 3e6],
                            {"base": {"pg": {"hits": 10, "n": 100}}})
        self.assertEqual(f["open"], 100)
        # mean 30 min, sd 15.8, se 7.07 -> 30 +- 13.9 min per system, x 100 open
        self.assertEqual((f["hours"]["lo"], f["hours"]["mid"], f["hours"]["hi"]), (26.9, 50.0, 73.1))
        self.assertEqual(f["hours"]["n"], 5)
        self.assertEqual(f["value"]["mid"], 50 * 2_000_000)
        m = forecast.mean_ci([2.0])
        self.assertEqual((m["lo"], m["mid"], m["n"]), (0.0, 2.0, 1))
        self.assertEqual(f["finds"]["mid"], 10.0)
        self.assertTrue(f["finds"]["lo"] < 10.0 < f["finds"]["hi"])
        self.assertFalse(f["thin"])
        self.assertTrue(forecast.sphere({"known": 5, "visited": 1}, [9], [])["thin"])
        self.assertIsNone(forecast.sphere(None, [1], [1]))

    def test_jumps(self):
        j = forecast.jumps(FuelStub(20.0, 2.0, 5.0, 40))
        self.assertEqual((j["mid"], j["lo"], j["hi"], j["n"], j["thin"]), (10, 9, 10, 40, False))
        self.assertTrue(forecast.jumps(FuelStub(20.0, 2.0, None, 2, "prior"))["thin"])
        self.assertIsNone(forecast.jumps(FuelStub(0.0, 2.0, 5.0, 40)))

    def test_bio_chance(self):
        rates = {"planets": 200, "with_bio": 20,
                 "atmo": [{"key": "Argon", "n": 19, "pct": 84.2, "lo": 62.4, "hi": 94.5}],
                 "pclass": [{"key": "Icy body", "n": 50, "pct": 8.0, "lo": 3.2, "hi": 18.8}]}
        c = forecast.bio_chance({"landable": 1, "atmo_type": "Argon", "planet_class": "Icy body"}, rates)
        self.assertEqual((c["pct"], c["basis"], c["n"]), (84.2, "atmosphere", 19))
        c = forecast.bio_chance({"landable": 1, "atmo_type": "Helium", "planet_class": "Icy body"}, rates)
        self.assertEqual((c["basis"], c["key"]), ("planet class", "Icy body"))
        c = forecast.bio_chance({"landable": 1, "atmo_type": None, "planet_class": "Rocky body"}, rates)
        self.assertEqual((c["basis"], c["pct"], c["n"]), ("all", 10.0, 200))
        self.assertIsNone(forecast.bio_chance({"landable": 0}, rates))


if __name__ == "__main__":
    unittest.main()
