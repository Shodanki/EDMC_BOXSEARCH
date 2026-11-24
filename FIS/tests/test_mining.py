# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""MINING: sessions from the journal; tritium in carrier jumps."""

import os
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

    def test_limpet_learning(self):
        """MO2 (5.1.0): recent sessions weigh more, the reserve follows the
        spread once five sessions of the hull are in; before that 10 %."""
        def run(i, lim, t):
            return {"start": 1000.0 * i, "total": t, "kind": "space", "asteroids": 30, "ship_type": "lakonminer",
                    "drones": {"prospector": lim // 3, "collection": lim - lim // 3}}
        # the developer's seven sessions, oldest first (17.11. measure: 0.37-0.47)
        seven = [run(i, lim, t) for i, (lim, t) in enumerate(
            [(89, 241), (97, 208), (89, 197), (105, 244), (126, 272), (112, 279), (103, 275)])]
        r = mining.limpet_ratio(seven)["by_type"]["lakonminer"]
        self.assertEqual(r["ratio"], 0.42)
        self.assertLess(r["recent"], r["ratio"], "the better recent sessions count more")
        self.assertTrue(r["learnt"])
        self.assertEqual(r["need"], 0)
        self.assertTrue(mining.RESERVE_MIN <= r["reserve"] <= mining.LIMPET_RESERVE)
        self.assertAlmostEqual(r["reserve"], min(mining.LIMPET_RESERVE, max(mining.RESERVE_MIN, r["spread"])), places=3)
        self.assertEqual(r["spread_of"], 7)
        three = mining.limpet_ratio(seven[:3])["by_type"]["lakonminer"]
        self.assertFalse(three["learnt"])
        self.assertEqual((three["need"], three["reserve"]), (2, mining.LIMPET_RESERVE))
        steady = [run(i, 100, 250) for i in range(6)]
        self.assertEqual(mining.limpet_ratio(steady)["all"]["reserve"], mining.RESERVE_MIN,
                         "no spread: the minimum reserve, never none")
        rat = mining.limpet_ratio(seven)
        plans = mining._limpet_plans(rat, [{"name": "MINER", "type": "Type-11", "type_key": "lakonminer",
                                            "cargo": 322, "current": False},
                                           {"name": "OTHER", "type": "Type-9", "type_key": "type9",
                                            "cargo": 256, "current": False}], 0)
        self.assertTrue(plans[0]["learnt"] and plans[0]["own"] and plans[0]["sessions"] == 7)
        self.assertEqual(plans[0]["limpets"], 147)          # 149 with the plain mean and 10 %
        self.assertFalse(plans[1]["learnt"] or plans[1]["own"])
        self.assertEqual(plans[1]["reserve"], mining.LIMPET_RESERVE)

    def test_limpet_spread_robust(self):
        """MO2b (user's test 24.11.): 38 sessions from the EDD history gave
        "spread ±59 %" - one 23 t session with 55 limpets and old technique.
        The spread is the median deviation of the last ten sessions."""
        def run(i, lim, t):
            return {"start": 1000.0 * i, "total": t, "kind": "space", "asteroids": 30, "ship_type": "lakonminer",
                    "drones": {"prospector": lim // 3, "collection": lim - lim // 3}}
        old = [run(i, 180, 260) for i in range(20)]                  # r 0.69, a year ago
        odd = [run(20, 55, 23)]                                      # r 2.4
        new = [run(21 + i, lim, t) for i, (lim, t) in enumerate(
            [(89, 241), (97, 208), (89, 197), (105, 244), (126, 272), (112, 279), (103, 275), (118, 244)])]
        r = mining.limpet_ratio(old + odd + new)["by_type"]["lakonminer"]
        self.assertEqual(r["spread_of"], mining.SPREAD_WINDOW)
        self.assertLess(r["spread"], 0.2, "one odd session and old technique do not blow it up")
        self.assertLessEqual(r["reserve"], mining.LIMPET_RESERVE)
        plans = mining._limpet_plans(mining.limpet_ratio(old + odd + new),
                                     [{"name": "MINER", "type": "Type-11", "type_key": "lakonminer",
                                       "cargo": 322, "current": False}], 0)
        self.assertEqual(plans[0]["spread_of"], mining.SPREAD_WINDOW)

    def test_collector_wave_singular(self):
        js = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "js", "views",
                               "mining.js"), encoding="utf-8").read()
        self.assertIn("({n} wave)", js)                         # singular, not "1 waves"

    def test_tritium_only_under_live(self):
        """User's test 24.11.: TRITIUM -> CARRIER stood under LIVE and HISTORY."""
        js = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "js", "views",
                               "mining.js"), encoding="utf-8").read()
        i = js.index('if (tab === "history") {')
        j = js.index('} else if (tab === "places") {', i)
        self.assertNotIn("tritium()", js[i:j])
        self.assertIn("limpets(), tritium()", js)

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


def _sec(t):
    """An event time t seconds after 08:00."""
    return "2026-05-30T08:%02d:%02dZ" % divmod(t, 60)


MULTI = "int_multidronecontrol_miningv2_size5_class5"


class CollectorLife(unittest.TestCase):
    """ML1: collector waves seen working - the journal writes no expiry."""

    def _events(self):
        def e(t, name, **kw):
            return dict({"timestamp": _sec(t), "event": name}, **kw)
        return [e(0, "Loadout", Ship="type9", Modules=[{"Slot": "Slot01", "Item": MULTI}]),
                e(5, "LaunchDrone", Type="Prospector"),
                e(10, "LaunchDrone", Type="Collection"), e(40, "LaunchDrone", Type="Collection"),   # one wave
                e(60, "MiningRefined", Type_Localised="Tritium"), e(130, "MiningRefined", Type_Localised="Tritium"),
                e(300, "LaunchDrone", Type="Collection"),                                       # the next wave
                e(400, "MiningRefined", Type_Localised="Tritium"),
                e(500, "LaunchDrone", Type="Collection")]                                        # nothing refined yet

    def test_waves_per_controller(self):
        life = mining.collector_life(self._events())
        self.assertEqual(list(life), [MULTI])
        c = life[MULTI]
        self.assertEqual((c["n"], c["median_s"], c["p90_s"], c["max_s"]), (2, 110, 120, 120))
        self.assertEqual(c["label"], {"kind": "mining", "grade": "5A"})
        self.assertEqual(mining.controller_label("int_dronecontrol_collection_size3_class2"),
                         {"kind": "collector", "grade": "3D"})
        self.assertIsNone(mining.controller_of({"Modules": [{"Item": "int_dronecontrol_prospector_size1_class5"}]}))

    def test_no_controller_no_waves(self):
        evs = [dict(x) for x in self._events() if x["event"] != "Loadout"]
        self.assertEqual(mining.collector_life(evs), {})

    def test_live_line(self):
        class A:
            def refresh(self, force=False):
                pass

            def events(self):
                return evs
        evs = self._events()
        now = parse_ts(_sec(560))
        out = mining.build_live(A(), {"loadout": None}, None, now)
        cl = out["collectors"]
        self.assertEqual((cl["last_wave_ago"], cl["life"]["max_s"], cl["label"]["grade"]), (60, 120, "5A"))


if __name__ == "__main__":
    unittest.main()
