# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""MINING: sessions from the journal; tritium in carrier jumps."""

import unittest

from fis import fleet as fl, mining
from fis.live import parse_ts


def ev(ts, name, **kw):
    return dict({"timestamp": "2026-05-30T%s:00Z" % ts, "event": name}, **kw)


ROCK = {"Materials": [{"Name": "Tritium", "Proportion": 31.5}, {"Name": "Water", "Proportion": 8.0}],
        "Content": "$AsteroidMaterialContent_High;", "Remaining": 100.0}

EVENTS = [
    ev("05:00", "LaunchDrone", Type="Prospector"),            # an older session
    ev("05:01", "MiningRefined", Type="$water_name;", Type_Localised="Water"),
    ev("07:00", "LaunchDrone", Type="Prospector"),
    ev("07:01", "ProspectedAsteroid", **dict(ROCK, Materials=[{"Name": "Tritium", "Proportion": 12.0}],
                                              Content="$AsteroidMaterialContent_Low;")),
    ev("07:02", "LaunchDrone", Type="Prospector"),
    ev("07:03", "ProspectedAsteroid", **ROCK),
    ev("07:04", "LaunchDrone", Type="Collection"),
    ev("07:05", "MiningRefined", Type="$tritium_name;", Type_Localised="Tritium"),
    ev("07:06", "MiningRefined", Type="$tritium_name;", Type_Localised="Tritium"),
    ev("07:07", "MiningRefined", Type="$tritium_name;", Type_Localised="Tritium"),
    ev("07:30", "LaunchDrone", Type="Repair"),                # no mining
]


class MiningTest(unittest.TestCase):
    def test_last_session(self):
        now = parse_ts("2026-05-30T07:20:00Z")
        s = mining.session(EVENTS, now)
        self.assertEqual(s["start"], parse_ts("2026-05-30T07:00:00Z"))   # 05:01 is two hours earlier
        self.assertTrue(s["active"])
        self.assertEqual(s["tritium"], 3)
        self.assertEqual(s["main"], "tritium")
        self.assertEqual(s["drones"], {"prospector": 2, "collection": 1})
        self.assertEqual(s["asteroids"], 2)
        self.assertEqual(s["best"]["share"], 31.5)
        self.assertEqual(s["best"]["content"], "high")
        self.assertEqual(s["last"]["materials"][0]["key"], "tritium")
        self.assertEqual(s["per_hour"], 9.0)            # 3 t in 20 minutes

    def test_ground_mining_with_the_rhino(self):
        """M2: refining while out in the SRV is a ground session of its own."""
        evs = EVENTS[:-1] + [
            ev("07:10", "LaunchSRV", SRVType="mev_rhino", SRVType_Localised="SRV Rhino"),
            ev("07:12", "MiningRefined", Type="$tantalum_name;", Type_Localised="Tantalum"),
            ev("07:13", "MiningRefined", Type="$tantalum_name;", Type_Localised="Tantalum"),
            ev("07:20", "DockSRV", SRVType="mev_rhino", SRVType_Localised="SRV Rhino"),
            ev("07:25", "MiningRefined", Type="$tritium_name;", Type_Localised="Tritium")]
        hs = mining.sessions(evs, parse_ts("2026-05-30T08:00:00Z"))
        kinds = [(h["kind"], h["vehicle"], h["main"], h["total"]) for h in hs]
        self.assertEqual(kinds, [("space", None, "water", 1), ("space", None, "tritium", 3),
                                 ("ground", "SRV Rhino", "tantalum", 2), ("space", None, "tritium", 1)])
        # the Nomad (LaunchVessel) counts as a vehicle too
        hs2 = mining.sessions([ev("09:00", "LaunchVessel", VesselType="lander01", VesselType_Localised="Nomad"),
                               ev("09:01", "MiningRefined", Type="$gold_name;")])
        self.assertEqual((hs2[0]["kind"], hs2[0]["vehicle"]), ("ground", "Nomad"))

    def test_limpet_ratio_skips_ground(self):
        space = {"total": 100, "kind": "space", "asteroids": 10,
                 "drones": {"prospector": 10, "collection": 30}}
        ground = {"total": 100, "kind": "ground", "asteroids": 0,
                  "drones": {"prospector": 0, "collection": 1}}
        r = mining.limpet_ratio([space, ground])["all"]
        self.assertEqual((r["sessions"], r["ratio"]), (1, 0.4))

    def test_ended_and_none(self):
        s = mining.session(EVENTS, parse_ts("2026-05-30T12:00:00Z"))
        self.assertFalse(s["active"])
        self.assertIsNone(mining.session([ev("07:30", "LaunchDrone", Type="Repair")]))

    def test_sessions_and_hotspots(self):
        hist = mining.sessions(EVENTS, parse_ts("2026-05-30T12:00:00Z"))
        self.assertEqual([h["main"] for h in hist], ["water", "tritium"])     # oldest first

        class FakeDb:
            def query(self, sql, args=()):
                row = lambda m, name, x: {"material": m, "label": None, "count": 1, "body_name": name + " A Ring",
                                          "ring_class": None, "system": name, "id64": 1, "x": x, "y": 0, "z": 0}
                return [row("Platinum", "Far", 50), row("Tritium", "Near", 3), row("Tritium", "Unknown", None)]
        hs = mining.hotspots_near(FakeDb(), (0, 0, 0))
        self.assertEqual([h["system"] for h in hs], ["Near", "Far", "Unknown"])
        self.assertEqual(hs[0]["key"], "tritium")
        self.assertIsNone(hs[2]["ly"])

    def test_limpet_load(self):
        # 0.42 limpets per tonne, 322 t: launched limpets free their space, so
        # 322 * 0.42 = 135.2 -> +10 % = 149; at the end ~14 spare, 308 t ore
        self.assertEqual(mining.limpet_load(322, 0.42), {"limpets": 149, "ore": 308})
        self.assertEqual(mining.room_for(120, 0.42), 206)        # 120 t free hold 206 t more ore
        self.assertEqual(mining.limpet_load(0, 0.42), {"limpets": 0, "ore": 0})
        runs = [{"total": 200, "asteroids": 30, "drones": {"prospector": 33, "collection": 55}, "ship_type": "lakonminer"},
                {"total": 5, "asteroids": 1, "drones": {"prospector": 9, "collection": 9}, "ship_type": "lakonminer"}]
        r = mining.limpet_ratio(runs)
        self.assertEqual(r["all"]["ratio"], 0.44)          # the 5 t session tells nothing
        self.assertEqual(r["by_type"]["lakonminer"]["sessions"], 1)
        self.assertEqual(r["all"]["per_rock_prospector"], 1.1)

    def test_type_key(self):
        self.assertEqual(mining.type_key("$tritium_name;"), "tritium")
        self.assertEqual(mining.type_key("LowTemperatureDiamond"), "lowtemperaturediamond")
        self.assertEqual(mining.content_level("$AsteroidMaterialContent_Medium;"), "medium")

    def test_carrier_trip(self):
        trip = fl.carrier_trip(1200, 5000, 1000)
        self.assertEqual(trip["jumps"], 3)
        self.assertTrue(trip["enough"])
        short = fl.carrier_trip(4000, 5000, 100)
        self.assertFalse(short["enough"])
        self.assertEqual(short["short"], short["need"] - 100)
        # the need is worked out for a carrier that carries it: starting with it, it is enough
        self.assertLessEqual(abs(fl.carrier_trip(4000, 5000, short["need"])["need"] - short["need"]), 1)


if __name__ == "__main__":
    unittest.main()
