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


def _burn(d, mass):
    """A size 7 drive: 1.2e-12 * (d * mass) ** 2.75 (20 ly at 1,921 t ~ 4.8 t)."""
    return 1.2e-12 * (d * mass) ** 2.75


def _panther(unladen=1857.0):
    return _e("14:00:01", "Loadout", Ship="panthermkii", ShipID=9, MaxJumpRange=30.0, UnladenMass=unladen,
              FuelCapacity={"Main": 64.0, "Reserve": 1.0},
              Modules=[{"Slot": "FrameShiftDrive", "Item": "int_hyperdrive_overcharge_size7_class5"}])


class TestFuelMass(unittest.TestCase):
    """SK2: every jump carries the ship's mass; the model fits dist * mass."""

    def _tracker(self):
        lt = LiveTracker(".")
        lt.feed(_e("14:00:00", "Commander", FID="F1", Name="Main"))
        lt.feed(_panther())
        for i, (d, cargo) in enumerate([(20.0, 0), (24.0, 0), (14.0, 1200), (16.0, 1200), (18.0, 1200)]):
            lt.feed(_e("14:%02d:00" % (i + 1), "Cargo", Vessel="Ship", Count=cargo))
            used = _burn(d, 1857.0 + 64.0 + cargo)
            lt.feed(_jump("14:%02d:30" % (i + 1), d, used, 64.0 - used))
        return lt

    def test_mass_per_jump(self):
        s = self._tracker().snapshot()
        self.assertEqual(len(s["jumps"]), 5)
        self.assertAlmostEqual(s["jumps"][0][2], 1857.0 + 64.0, places=6)
        self.assertAlmostEqual(s["jumps"][2][2], 1857.0 + 64.0 + 1200.0, places=6)

    def test_model_learnt_with_mass(self):
        cfg_tmp = tempfile.mkdtemp()
        make_cfg(fx.make_db(os.path.join(cfg_tmp, "db.sqlite")), cfg_tmp)
        from fis import model
        live = self._tracker().snapshot()
        m = model.build_ship(live)["fuel"]["model"]
        self.assertEqual((m["source"], m["mass"], m["n"]), ("fit", True, 5))
        self.assertAlmostEqual(m["power"], 2.75, places=3)
        fs = model._fuel_state(live)
        self.assertAlmostEqual(fs.cost_of(20.0), _burn(20.0, 1857.0 + fs.level + 1200.0),
                               delta=0.01 * _burn(20.0, 3121.0))

    def test_refit_is_another_history(self):
        lt = self._tracker()
        lt.feed(_panther(unladen=1757.0))          # 100 t lighter: another mass step
        self.assertEqual(lt.snapshot()["jumps"], [])
        lt.feed(_e("15:00:00", "LoadGame", Commander="Main", Ship="panthermkii", ShipID=9))
        self.assertEqual(lt.snapshot()["jumps"], [])  # LoadGame keeps the step
        lt.feed(_panther(unladen=1860.0))
        self.assertEqual(len(lt.snapshot()["jumps"]), 5)


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
