# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""ST3/ST4/ST5 (5.1.0): travel per day/week/month, ships compared, bio catalogue."""

import calendar
import unittest

from fis import careerstats as cs

NOW = calendar.timegm((2026, 11, 24, 12, 0, 0, 0, 0, 0))     # a Tuesday


def ts(day, hour=10, month=11):
    return "2026-%02d-%02dT%02d:00:00Z" % (month, day, hour)


EVS = [
    {"event": "Loadout", "timestamp": ts(1, 9), "ShipID": 5, "ShipName": "EXPLORER", "Ship": "Krait_Light"},
    {"event": "FSDJump", "timestamp": ts(23, 9), "SystemAddress": 1, "StarSystem": "A", "JumpDist": 40.0},
    {"event": "Scan", "timestamp": ts(23, 9), "SystemAddress": 1, "BodyID": 1},
    {"event": "Scan", "timestamp": ts(23, 9), "SystemAddress": 1, "BodyID": 1},                 # again: once
    {"event": "Docked", "timestamp": ts(23, 9)},
    {"event": "FSDJump", "timestamp": ts(24, 9), "SystemAddress": 2, "StarSystem": "B", "JumpDist": 30.0},
    {"event": "FSDJump", "timestamp": ts(24, 9), "SystemAddress": 1, "StarSystem": "A", "JumpDist": 30.0},  # not new
    {"event": "Loadout", "timestamp": ts(24, 10), "ShipID": 6, "ShipName": " ", "Ship": "Corsair"},
    {"event": "FSDJump", "timestamp": ts(24, 10), "SystemAddress": 3, "StarSystem": "C", "JumpDist": 20.0},
    {"event": "Died", "timestamp": ts(24, 10)},
    {"event": "ScanOrganic", "timestamp": ts(20), "ScanType": "Analyse", "Genus_Localised": "Bacterium",
     "Species_Localised": "Bacterium Informem", "Variant_Localised": "Bacterium Informem - Lime"},
    {"event": "ScanOrganic", "timestamp": ts(21), "ScanType": "Analyse", "Genus_Localised": "Bacterium",
     "Species_Localised": "Bacterium Informem", "Variant_Localised": "Bacterium Informem - Red"},
    {"event": "ScanOrganic", "timestamp": ts(21), "ScanType": "Log", "Genus_Localised": "Tussock",
     "Species_Localised": "Tussock Pennata"},                                                   # only logged
    {"event": "ScanOrganic", "timestamp": ts(22), "ScanType": "Analyse", "Genus_Localised": "Bacterium",
     "Species_Localised": "Bacterium Vesicula"},
]


class CareerStatsTest(unittest.TestCase):
    def test_travel_grid(self):
        tr = cs.travel(sorted(EVS, key=lambda e: e["timestamp"]), NOW)
        days = {c["start"]: c for c in tr["day"]}
        today = days[calendar.timegm((2026, 11, 24, 0, 0, 0, 0, 0, 0))]
        self.assertEqual((today["jumps"], today["ly"], today["new"]), (3, 80, 2), "A was visited the day before")
        self.assertEqual(len(tr["day"]), 12)
        self.assertEqual(tr["week"][-1]["start"], calendar.timegm((2026, 11, 23, 0, 0, 0, 0, 0, 0)), "weeks start Monday")
        self.assertEqual(tr["week"][-1]["jumps"], 4)
        self.assertEqual(tr["month"][-1]["start"], calendar.timegm((2026, 11, 1, 0, 0, 0, 0, 0, 0)))
        self.assertEqual(tr["month"][-1]["scans"], 1, "each body once")
        self.assertEqual(tr["month"][0]["start"], calendar.timegm((2025, 12, 1, 0, 0, 0, 0, 0, 0)))
        self.assertEqual((tr["since_dock"]["jumps"], tr["since_dock"]["ly"]), (3, 80))

    def test_ships(self):
        rows = {r["id"]: r for r in cs.ships(sorted(EVS, key=lambda e: e["timestamp"]))}
        self.assertEqual((rows[5]["name"], rows[5]["jumps"], rows[5]["ly"], rows[5]["systems"]), ("EXPLORER", 3, 100, 2))
        self.assertEqual((rows[6]["name"], rows[6]["type"], rows[6]["lost"]), (None, "corsair", 1), "a blank name is none")

    def test_bio_catalogue(self):
        cat = cs.bio_catalogue(EVS, {"Bacterium Informem": {"value": 8418000}})
        self.assertEqual([g["genus"] for g in cat], ["Bacterium"], "only analysed species")
        b = cat[0]
        self.assertEqual((len(b["species"]), b["analysed"]), (2, 3))
        inf = b["species"][0]
        self.assertEqual((inf["species"], inf["variants"], inf["value"], inf["analysed"]),
                         ("Bacterium Informem", ["Lime", "Red"], 8418000, 2))


if __name__ == "__main__":
    unittest.main()
