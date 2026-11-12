# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""S2: docked stations and carriers beside their body in the SYSTEM map -
matched on the distance from the arrival star (Docked DistFromStarLS against
the scans' DistanceFromArrivalLS), never guessed."""

import unittest

from fis.live import parse_ts
from tests import fixtures as fx
from tests.test_api import _Base

ROWS = [{"body_id": 0, "name": "Test A", "arrival_ls": 0.0},
        {"body_id": 3, "name": "Test A 1", "arrival_ls": 79.2},
        {"body_id": 4, "name": "Test A 1 a", "arrival_ls": 79.9},
        {"body_id": 9, "name": "Test A 5", "arrival_ls": 2412.0}]
BODIES = [{"body_id": 3, "short": "A 1"}, {"body_id": 4, "short": "A 1 a"}, {"body_id": 9, "short": "A 5"}]
NOW = parse_ts("2026-11-12T20:00:00Z")


class Places(_Base):
    def place(self, pois):
        self.model.place_pois(pois, ROWS, BODIES, NOW)
        return pois

    def test_station_beside_the_matching_body(self):
        p = self.place([{"kind": "station", "name": "Ryman Enterprise", "_dist": 79.406858,
                         "seen": "2026-05-21T17:34:05Z"}])[0]
        self.assertEqual((p["near"]["body_id"], p["near"]["short"]), (3, "A 1"))   # 0.21 LS off, the moon 0.49
        self.assertNotIn("_dist", p)

    def test_far_out_uses_the_relative_tolerance(self):
        p = self.place([{"kind": "station", "name": "Far Port", "_dist": 2418.0}])[0]
        self.assertEqual(p["near"]["body_id"], 9)                                   # 6 LS off, 0.25 %

    def test_no_matching_body_no_place(self):
        p = self.place([{"kind": "station", "name": "Nowhere", "_dist": 400.0}])[0]
        self.assertNotIn("near", p)
        self.assertNotIn("_dist", p)

    def test_carriers_only_while_fresh(self):
        fresh, old = self.place([
            {"kind": "carrier", "name": "X1Y-2Z3", "_dist": 79.3, "seen": "2026-11-12T08:00:00Z"},
            {"kind": "carrier", "name": "A1B-2C3", "_dist": 79.3, "seen": "2026-11-10T08:00:00Z"}])
        self.assertEqual((fresh["near"]["body_id"], fresh["near"]["fresh"]), (3, True))
        self.assertEqual((old["near"]["body_id"], old["near"]["fresh"]), (3, False))  # two days ago

    def test_map_places_own_favourites_others(self):
        from fis import carriers
        poi = [{"kind": "station", "name": "Port", "near": {"body_id": 3}},
               {"kind": "station", "name": "Seen only in the FSS"},
               {"kind": "carrier", "name": "OWN-001", "near": {"body_id": 3, "fresh": True}},
               {"kind": "carrier", "name": "FAV ONE X1Y-2Z3", "favourite": True, "callsign": "X1Y-2Z3",
                "near": {"body_id": 3, "fresh": False}},
               {"kind": "carrier", "name": "OLD A1B-2C3", "near": {"body_id": 3, "fresh": False}},
               {"kind": "carrier", "name": "NEW Q1Q-1Q1", "near": {"body_id": 4, "fresh": True}},
               {"kind": "carrier", "name": "FAV GONE K7K-7K7", "favourite": True, "callsign": "K7K-7K7",
                "near": {"body_id": 3, "fresh": True}}]
        here = [{"kind": "favourite", "callsign": "X1Y-2Z3", "name": "FAV ONE", "source": "journal"},
                {"kind": "favourite", "callsign": "S5S-5S5", "name": "FAV SPANSH", "source": "Spansh",
                 "ts": "2026-11-12T08:00:00Z"}]
        out, extra = carriers.map_places(poi, "OWN-001", here)
        drawn = {p["name"]: p.get("map") for p in out}
        self.assertEqual(drawn, {"Port": True, "Seen only in the FSS": False, "OWN-001": False,
                                 "FAV ONE X1Y-2Z3": True, "OLD A1B-2C3": False,
                                 "NEW Q1Q-1Q1": True,
                                 "FAV GONE K7K-7K7": False})    # docked today, but newest position elsewhere
        self.assertTrue(out[2]["own"])                          # drawn by the own-carrier layer only
        self.assertEqual([(e["callsign"], e["here_source"], e["map"]) for e in extra],
                         [("S5S-5S5", "Spansh", True)])        # known here only from Spansh: beside the star
        self.assertNotIn("map", poi[0])                         # the cached list stays untouched
        self.assertEqual(carriers.map_places([], "OWN-001", [{"callsign": "OWN-001"}])[1], [])

    def test_settlements_and_undocked_stay_as_they_are(self):
        s, u = self.place([{"kind": "settlement", "name": "Camp", "body": "A 1"},
                           {"kind": "station", "name": "Seen only in the FSS"}])
        self.assertNotIn("near", s)
        self.assertNotIn("near", u)

    def test_build_system_never_leaks_the_raw_distance(self):
        class Ar:
            def refresh(self):
                pass

            def events(self):
                return [{"event": "Docked", "SystemAddress": fx.SYS_ID, "StationName": "Test Port",
                         "StationType": "Outpost", "DistFromStarLS": 512.3,
                         "timestamp": "2026-11-03T10:00:00Z"}]

        out = self.model.build_system(self.db, fx.SYS_ID, archive=Ar())
        self.assertTrue(out["poi"])
        self.assertFalse(any("_dist" in p for p in out["poi"]))


if __name__ == "__main__":
    unittest.main()
