# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""V1: the vehicle tab from what the game writes - shaped after the Nomad,
Scarab and Rhino recording of 11.11.2026 (Status.json in the vehicle: main
tank 0, the reservoir is the vehicle's own tank)."""

import unittest

from fis.config import Config
from fis.live import LiveTracker

from tests import fixtures as fx

BODY = "Test 1"
SHIP, SRV, LANDED, GEAR, LIGHTS, ASSIST = 1 << 24, 1 << 26, 1 << 1, 1 << 2, 1 << 8, 1 << 15


def ev(t, name, **kw):
    return dict({"timestamp": "2026-11-11T17:%sZ" % t, "event": name}, **kw)


def st(t, flags, lat, lon, fuel=None, cargo=0.0, flags2=0, alt=0.0):
    s = {"timestamp": "2026-11-11T17:%sZ" % t, "event": "Status", "Flags": flags, "Flags2": flags2,
         "Latitude": lat, "Longitude": lon, "Heading": 90, "Altitude": alt, "BodyName": BODY,
         "PlanetRadius": 1_000_000.0, "Pips": [4, 4, 4], "FireGroup": 0, "LegalState": "Clean"}
    if fuel is not None:
        s["Fuel"] = fuel
        s["Cargo"] = cargo
    return s


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cfg = Config()
        cfg.plugin_dir = fx.PLUGIN_DIR
        cfg.use_plugin_path()
        from fis import model
        cls.model = model

    def setUp(self):
        self.lt = LiveTracker(".")
        self.lt.feed(ev("00:00", "FSDJump", StarSystem="Test", SystemAddress=1, StarPos=[0, 0, 0],
                        FuelLevel=170.0))
        # the ship, landed at 0/0
        self.lt.feed_status(st("00:10", SHIP | LANDED, 0.0, 0.0, {"FuelMain": 170.0, "FuelReservoir": 0.6}))

    def view(self, t):
        from fis.live import parse_ts
        return self.model.build_vehicle(self.lt.snapshot(), now=parse_ts("2026-11-11T17:%sZ" % t))


class TestVehicle(_Base):
    def test_nothing_out(self):
        v = self.view("00:20")
        self.assertFalse(v["active"])
        self.assertIsNone(v["vehicle"])

    def test_rhino_trip(self):
        self.lt.feed(ev("01:00", "LaunchSRV", SRVType="mev_rhino", SRVType_Localised="SRV Rhino",
                        Loadout="base", ID=50, PlayerControlled=True))
        self.lt.feed_status(st("01:05", SRV | ASSIST | LIGHTS, 0.01, 0.0, {"FuelMain": 0.0, "FuelReservoir": 0.6}))
        for i in range(3):
            self.lt.feed(ev("02:0%d" % i, "MiningRefined", Type="$haematite_name;", Type_Localised="Haematite"))
        self.lt.feed(ev("02:05", "Cargo", Vessel="SRV", Count=3))
        self.lt.feed_status(st("03:00", SRV | ASSIST | LIGHTS, 0.0, 0.01, {"FuelMain": 0.0, "FuelReservoir": 0.55}, 3.0))
        snap = self.lt.snapshot()
        self.assertEqual(snap["fuel"]["main"], 170.0)        # the ship's tank is not emptied
        v = self.view("03:00")["vehicle"]
        self.assertEqual((v["name"], v["edition"], v["nomad"]), ("SRV Rhino", "base", False))
        self.assertEqual(v["refined"], {"Haematite": 3})
        self.assertEqual(v["cargo"], 3.0)
        self.assertAlmostEqual(v["fuel_used"], 0.05, places=3)
        self.assertIn("drive_assist", v["flags"])
        self.assertIn("lights", v["flags"])
        self.assertAlmostEqual(v["ship"]["dist_m"], 175.0, delta=2.0)   # 0.01 deg on a 1000 km body
        self.assertAlmostEqual(v["ship"]["bearing"], 270.0, delta=1.0)  # ship lies west
        # back aboard: the trip stays as the last one, a late status makes no phantom
        self.lt.feed(ev("04:00", "DockSRV", SRVType="mev_rhino", SRVType_Localised="SRV Rhino", ID=50))
        self.lt.feed_status(st("04:01", SRV | ASSIST, 0.0, 0.0, {"FuelMain": 0.0, "FuelReservoir": 0.55}, 3.0))
        out = self.view("05:00")
        self.assertFalse(out["active"])
        self.assertEqual(out["last"]["how"], "docked")
        self.assertEqual(out["last"]["refined"], {"Haematite": 3})

    def test_nomad_flies_lands_and_samples_on_foot(self):
        self.lt.feed(ev("01:00", "LaunchVessel", VesselType="lander01", VesselType_Localised="Nomad",
                        Loadout="galactic", ID=49, PlayerControlled=True))
        self.lt.feed_status(st("01:05", SRV | GEAR, 0.0, 0.02, {"FuelMain": 0.0, "FuelReservoir": 0.5}, alt=1300.0))
        v = self.view("01:05")["vehicle"]
        self.assertTrue(v["nomad"] and v["flying"])
        self.assertEqual(v["edition"], "galactic")
        self.assertIn("gear", v["flags"])
        self.lt.feed(ev("01:30", "Touchdown", PlayerControlled=True, Body=BODY, Latitude=0.0, Longitude=0.02))
        self.lt.feed(ev("01:40", "Disembark", SRV=True))
        self.lt.feed_status(st("01:45", 0, 0.0, 0.021, flags2=1 | (1 << 4)))
        self.lt.feed(ev("02:00", "ScanOrganic", ScanType="Sample", Body=7))
        v = self.view("02:00")["vehicle"]
        self.assertTrue(v["on_foot"])
        self.assertEqual((v["landings"], v["samples"]), (1, 1))
        self.assertEqual(v["flags"], [])

    def test_lost_on_death(self):
        self.lt.feed(ev("01:00", "LaunchSRV", SRVType="testbuggy", SRVType_Localised="SRV Scarab",
                        Loadout="starter", ID=51))
        self.lt.feed(ev("02:00", "Died"))
        out = self.view("02:10")
        self.assertFalse(out["active"])
        self.assertEqual(out["last"]["how"], "lost")


if __name__ == "__main__":
    unittest.main()
