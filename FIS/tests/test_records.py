# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""ST2/ST6/ST8/ST9 (5.1.0): RECORDS & ATLAS from the commander's own journals."""

import os
import unittest

from fis import fleet, records

G = records.G


def scan(sys_id, body_id, name, ts="2026-11-01T10:00:00Z", **kw):
    return dict({"event": "Scan", "timestamp": ts, "SystemAddress": sys_id, "BodyID": body_id, "BodyName": name,
                 "StarSystem": name.split(" ")[0]}, **kw)


def jump(ts, pos, dist, name="Sys", sid=1):
    return {"event": "FSDJump", "timestamp": ts, "StarPos": pos, "JumpDist": dist, "StarSystem": name, "SystemAddress": sid}


EVS = [
    scan(1, 0, "Alpha A", StarType="K", Radius=records.SUN_RADIUS_M * 2, StellarMass=0.8, SurfaceTemperature=4500,
         DistanceFromArrivalLS=0, RotationPeriod=90000),
    scan(1, 0, "Alpha A", StarType="K", Radius=records.SUN_RADIUS_M * 99, DistanceFromArrivalLS=0),      # again: once
    scan(2, 0, "Beta A", StarType="DA", Radius=7e6, StellarMass=1.1, SurfaceTemperature=20000, DistanceFromArrivalLS=0,
         RotationPeriod=3.5),
    scan(2, 3, "Beta 3", PlanetClass="Earthlike body", Radius=6.4e6, MassEM=1.0, SurfaceGravity=9.80665,
         SurfaceTemperature=290, WasDiscovered=False),
    scan(2, 4, "Beta 4", PlanetClass="Icy body", Radius=3.0e5, MassEM=0.001, SurfaceGravity=2.9, SurfaceTemperature=40,
         TerraformState="Terraformable", WasDiscovered=True),
    scan(2, 5, "Beta 5", PlanetClass="High metal content body", Radius=7.0e6, MassEM=9.0, SurfaceGravity=30.0,
         SurfaceTemperature=900),
    {"event": "Touchdown", "timestamp": "2026-11-02T10:00:00Z", "SystemAddress": 2, "BodyID": 4, "Body": "Beta 4",
     "PlayerControlled": True},
    jump("2026-11-01T09:00:00Z", [0, 0, 100], 40.0, "Near", 10),
    jump("2026-11-01T09:30:00Z", [0, 0, 160], 60.5, "Far", 11),
    jump("2026-11-03T09:00:00Z", [0, 0, 120], 40.0, "Back", 12),
    jump("2020-11-26T10:00:00Z", [0, 0, 25900], 50.0, "Core", None),          # EDD archive: no SystemAddress
    {"event": "CodexEntry", "timestamp": "2026-11-01T09:40:00Z", "SystemAddress": 11, "Name_Localised": "Bacterium"},
]


class RecordsTest(unittest.TestCase):
    def test_personal_records(self):
        rec = {r["key"]: r for r in records.personal_records(EVS)}
        self.assertEqual(rec["star_biggest"]["value"], 2.0, "each body once - the first scan")
        self.assertEqual((rec["star_hottest"]["value"], rec["star_hottest"]["body"]), (20000, "Beta A"))
        self.assertEqual(rec["planet_smallest"]["value"], 300)
        self.assertEqual(rec["gravity_scanned"]["value"], round(30.0 / G, 2))
        self.assertEqual((rec["gravity_landed"]["value"], rec["gravity_landed"]["body"]), (round(2.9 / G, 2), "Beta 4"))
        self.assertEqual((rec["planet_coldest"]["value"], rec["planet_hottest"]["value"]), (40, 900))
        self.assertEqual(rec["spin_fastest"]["value"], 3.5)
        self.assertEqual(rec["jump_longest"]["value"], 60.5)
        self.assertEqual((rec["farthest_sol"]["value"], rec["farthest_sol"]["system"]), (25900.0, "Core"))
        self.assertEqual(rec["jumps_one_day"]["value"], 2)
        self.assertEqual([r["key"] for r in records.personal_records(EVS)],
                         [k for k in records.RECORD_ORDER if k in rec], "in the fixed order")

    def test_regions(self):
        def region(x, y, z):
            return (1, "Galactic Centre") if z > 20000 else (18, "Inner Orion Spur")
        r = records.regions(EVS, region, ["Galactic Centre", "Inner Orion Spur", "The Abyss"])
        self.assertEqual([(v["name"], v["jumps"], v["systems"], v["bio"]) for v in r["visited"]],
                         [("Inner Orion Spur", 3, 3, 1), ("Galactic Centre", 1, 1, 0)])
        self.assertEqual((r["total"], r["unvisited"]), (3, ["The Abyss"]))
        self.assertEqual(records.regions(EVS, None, ["A", "B"])["visited"], [])

    def test_stars_and_worlds(self):
        s = records.stars_and_worlds(EVS)
        self.assertEqual(s["stars"], [{"group": "K", "n": 1}, {"group": "white dwarf", "n": 1}])
        w = {x["kind"]: x for x in s["worlds"]}
        self.assertEqual((w["Earthlike body"]["found"], w["Earthlike body"]["first"]), (1, 1))
        self.assertEqual((w["terraformable"]["found"], w["terraformable"]["first"]), (1, 0))
        self.assertEqual(records.star_group("K_OrangeGiant"), "K giant")
        self.assertEqual(records.star_group("H"), "black hole")

    def test_journey(self):
        j = records.journey(EVS)
        self.assertEqual(j["days"], 3)
        self.assertEqual((j["now"], j["max"], j["ly"]), (120.0, 25900.0, 190))        # 190.5 rounds to even
        self.assertEqual(j["points"][1][1], 160.0, "the last jump of the day counts")

    def test_archive_keeps_what_records_need(self):
        slim = fleet._slim_scan(dict(scan(1, 2, "X 1", PlanetClass="Icy body"), Radius=1.0, SurfaceGravity=2.0,
                                     SurfaceTemperature=3.0, RotationPeriod=4.0, Materials=[{"Name": "iron"}]))
        for k in ("Radius", "SurfaceGravity", "SurfaceTemperature", "RotationPeriod"):
            self.assertIn(k, slim)
        self.assertNotIn("Materials", slim, "still slim")

    def test_sub_tab(self):
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "js", "views",
                               "statistics.js"), encoding="utf-8") as fh:
            js = fh.read()
        self.assertIn('["atlas", N_("RECORDS & ATLAS"), [[["records"], ["regions"]], [["starsWorlds"], ["journey"]]]]', js)


if __name__ == "__main__":
    unittest.main()
