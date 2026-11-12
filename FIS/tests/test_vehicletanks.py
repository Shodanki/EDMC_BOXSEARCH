# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""V1b: the vehicle's tank size, learnt from the full tank right after a
refuel synthesis (Scarab, 12.11.2026: 0.488 -> 0.500 t two seconds after
"Fuel Basic")."""

import os
import tempfile
import unittest

from fis.vehicletanks import VehicleTankStore
from tests.test_vehicle import SRV, _Base, ev, st


class TankFromSynthesis(_Base):
    def _out(self):
        self.lt.feed(ev("01:00", "LaunchSRV", SRVType="testbuggy", SRVType_Localised="SRV Scarab",
                        Loadout="starter", ID=51))
        self.lt.feed_status(st("01:05", SRV, 0.01, 0.0, {"FuelMain": 0.0, "FuelReservoir": 0.488}))

    def test_full_tank_after_fuel_synthesis(self):
        self._out()
        self.assertIsNone(self.lt.snapshot()["srv"].get("tank_full"))
        self.lt.feed(ev("01:40", "Synthesis", Name="Fuel Basic",
                        Materials=[{"Name": "sulphur", "Count": 1}, {"Name": "phosphorus", "Count": 1}]))
        self.lt.feed_status(st("01:42", SRV, 0.01, 0.0, {"FuelMain": 0.0, "FuelReservoir": 0.5}))
        full = self.lt.snapshot()["srv"]["tank_full"]
        self.assertEqual(full["t"], 0.5)
        # with the size known the view shows the fill against it
        v = self.model.build_vehicle(self.lt.snapshot(), tanks={"testbuggy": {"t": 0.5, "ts": "x"}})
        self.assertEqual((v["vehicle"]["capacity"], v["vehicle"]["fuel_pct"]), (0.5, 100.0))

    def test_other_synthesis_or_late_reading_teach_nothing(self):
        self._out()
        self.lt.feed(ev("01:40", "Synthesis", Name="Ammo Basic",
                        Materials=[{"Name": "sulphur", "Count": 2}, {"Name": "phosphorus", "Count": 1}]))
        self.lt.feed_status(st("01:42", SRV, 0.01, 0.0, {"FuelMain": 0.0, "FuelReservoir": 0.47}))
        self.assertIsNone(self.lt.snapshot()["srv"].get("tank_full"))
        self.lt.feed(ev("02:00", "Synthesis", Name="Fuel Basic", Materials=[]))
        self.lt.feed_status(st("02:30", SRV, 0.01, 0.0, {"FuelMain": 0.0, "FuelReservoir": 0.46}))
        self.assertIsNone(self.lt.snapshot()["srv"].get("tank_full"))     # 30 s later: no proof

    def test_no_capacity_no_pct(self):
        self._out()
        v = self.model.build_vehicle(self.lt.snapshot(), tanks={"mev_rhino": {"t": 1.0}})["vehicle"]
        self.assertNotIn("capacity", v)
        self.assertNotIn("fuel_pct", v)


class Store(unittest.TestCase):
    def test_learn_keep_and_bad_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "vehicle_tanks.json")
            s = VehicleTankStore(p)
            self.assertEqual(s.all(), {})
            self.assertTrue(s.learn("testbuggy", 0.5, "SRV Scarab", "2026-11-12T17:41:01Z"))
            self.assertFalse(s.learn("testbuggy", 0.5))                 # same value: no write
            self.assertFalse(s.learn("../x", 0.5))
            self.assertFalse(s.learn("mev_rhino", 0))
            self.assertFalse(s.learn("mev_rhino", 32.0))                # a ship's tank, not a vehicle's
            self.assertEqual(VehicleTankStore(p).get("testbuggy")["t"], 0.5)
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("{broken")
            self.assertEqual(VehicleTankStore(p).all(), {})
            self.assertTrue(os.path.exists(p + ".bad"))
            with open(p + ".bad", encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "{broken")
            self.assertFalse(os.path.exists(p))


if __name__ == "__main__":
    unittest.main()
