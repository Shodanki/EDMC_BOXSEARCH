# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""The fuel model learns per ship and commander (11.11.: another commander's
ship made a Caspian look like 6 jumps of fuel); no warning before a jump to
a scoopable star."""

import os
import tempfile
import unittest

from fis.data import Database
from fis.live import LiveTracker

from . import fixtures as fx
from .test_api import make_cfg


def _e(t, ev, **kw):
    return dict({"timestamp": "2026-11-11T%sZ" % t, "event": ev}, **kw)


def _jump(t, ly, used, level):
    return _e(t, "FSDJump", StarSystem="S%s" % t, SystemAddress=hash(t) & 0xFFFF,
              StarPos=[0, 0, 0], JumpDist=ly, FuelUsed=used, FuelLevel=level)


SMALL = [_e("09:00:00", "Commander", FID="F2", Name="Second"),
         _e("09:00:01", "LoadGame", Commander="Second", Ship="krait_light", ShipID=7, FuelCapacity=32.0, FuelLevel=32.0),
         _e("09:00:02", "Loadout", Ship="krait_light", ShipID=7, MaxJumpRange=45.0,
            FuelCapacity={"Main": 32.0, "Reserve": 0.6})] + \
    [_jump("09:%02d:00" % i, 42.0, 6.5, 30.0) for i in range(1, 9)]
BIG = [_e("12:00:00", "Commander", FID="F1", Name="Main"),
       _e("12:00:01", "LoadGame", Commander="Main", Ship="explorer_nx", ShipID=3, FuelCapacity=176.0, FuelLevel=176.0),
       _e("12:00:02", "Loadout", Ship="explorer_nx", ShipID=3, MaxJumpRange=68.3,
          FuelCapacity={"Main": 176.0, "Reserve": 1.14}),
       _jump("12:10:00", 12.889, 0.130244, 175.87),
       _jump("12:20:00", 7.525, 0.033826, 174.7)]


class TestFuelPerShip(unittest.TestCase):
    def test_jumps_kept_apart(self):
        lt = LiveTracker(".")
        for e in SMALL + BIG:
            lt.feed(e)
        s = lt.snapshot()
        self.assertEqual(len(s["jumps"]), 2)                       # only the Caspian's
        for e in SMALL[:3]:                                        # back to the small ship
            lt.feed(e)
        self.assertEqual(len(lt.snapshot()["jumps"]), 8)

    def test_plugin_fuelstate(self):
        cfg_tmp = tempfile.mkdtemp()
        make_cfg(fx.make_db(os.path.join(cfg_tmp, "db.sqlite")), cfg_tmp)
        from fis import model
        ds = model.plugin().deepspace
        fs = ds.FuelState(176.0, 175.0, 68.3)
        fs.set_ship(("Second", 7))
        for _ in range(8):
            fs.add_jump(42.0, 6.5)
        fs.set_ship(("Main", 3))
        fs.add_jump(12.889, 0.130244)
        fs.add_jump(7.525, 0.033826)
        self.assertEqual(len(fs.jumps), 2)
        self.assertGreaterEqual(fs.jumps_left, 10)
        self.assertIsNone(fs.warning())
        fs.set_ship(("Second", 7))
        self.assertEqual(len(fs.jumps), 8)


class TestScoopableTarget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="fis-fuel-")
        path = fx.make_db(os.path.join(cls.tmp, "db.sqlite"))
        make_cfg(path, cls.tmp)
        cls.db = Database(path)
        from fis import model
        cls.model = model

    def _briefing(self, star):
        lt = LiveTracker(".")
        for e in BIG:
            lt.feed(e)
        live = lt.snapshot()
        live["fuel"]["main"] = 60.0          # 4 full-range jumps: "fuel low"
        live["system"]["pos"] = [100.0, -20.0, 43.0]
        live["target"] = {"name": fx.SYS, "id64": fx.SYS_ID, "star_class": star}
        return self.model.build_briefing(self.db, live)["fuel"]

    def test_warning_only_when_the_target_cannot_refuel(self):
        f = self._briefing("L")            # brown dwarf: not scoopable
        self.assertTrue(f["warning"])
        self.assertTrue(f.get("scoop_at_target") is None)
        g = self._briefing("G")
        self.assertIsNone(g["warning"])
        self.assertTrue(g["scoop_at_target"])


if __name__ == "__main__":
    unittest.main()
