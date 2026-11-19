# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
The fuel model with the ship's mass (SK2, 5.0).

The drive burns fuel = l * (dist * mass / optimal mass) ** power. Up to 4.12
the plugin fitted used = a * dist ** b; a ship whose mass changes (a hold
filled with 1,200 t, a tank run down) scattered by 32 % around that curve
on the developer's journals, and by 0-12 % with the mass. These tests feed
journal-shaped events through deepspace.FuelState.feed, as the plugin and
the journal replay do.

    python tests/fuel_model.py      (from the plugin folder)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import deepspace as ds  # noqa: E402

FSD7 = "int_hyperdrive_overcharge_size7_class5"
L_CONST, POWER = 1.2e-12, 2.75      # a size 7 drive: 20 ly at 1,921 t ~ 4.8 t


def loadout(ship_id=9, unladen=1857.0, item=FSD7, cap=64.0):
    """A Loadout event with the fields the model reads."""
    return {"event": "Loadout", "Ship": "panthermkii", "ShipID": ship_id, "UnladenMass": unladen,
            "MaxJumpRange": 30.0, "FuelCapacity": {"Main": cap, "Reserve": 1.0},
            "Modules": [{"Slot": "FrameShiftDrive", "Item": item}]}


def burn(d, mass):
    """What the game's drive would use for a jump of d ly at that mass."""
    return L_CONST * (d * mass) ** POWER


def fly(fs, hops, cargo=0.0, level=64.0, unladen=1857.0):
    """Jumps as FSDJump events, each with the fuel the drive really burns."""
    fs.feed({"event": "Cargo", "Vessel": "Ship", "Count": cargo})
    for d in hops:
        used = burn(d, unladen + level + cargo)
        level -= used
        fs.feed({"event": "FSDJump", "JumpDist": d, "FuelUsed": used, "FuelLevel": level})
        level = 64.0                         # scooped full again
    return level


class FuelModel(unittest.TestCase):
    """deepspace.FuelState with the mass in the curve."""

    def test_fsd_power(self):
        """The prior power comes from the drive's size."""
        self.assertEqual(ds.fsd_power(FSD7), 2.75)
        self.assertEqual(ds.fsd_power("int_hyperdrive_size5_class5"), 2.45)
        self.assertEqual(ds.fsd_power("int_hyperdrive_overcharge_size8_class5_overchargebooster_mkii"), 2.5)
        self.assertIsNone(ds.fsd_power("int_shieldgenerator_size5_class5"))
        self.assertIsNone(ds.fsd_power(None))

    def test_mass_in_the_fit(self):
        """Empty and with 1,200 t in the hold: one curve over dist * mass
        fits both, a curve over the distance alone does not."""
        fs = ds.FuelState()
        fs.feed(loadout(), "Cmdr")
        fly(fs, [20.0, 24.0, 28.0])
        fly(fs, [14.0, 16.0, 18.0], cargo=1200.0)
        lm = fs.learned()
        self.assertEqual(lm["source"], "fit")
        self.assertTrue(lm["mass"])
        self.assertEqual(lm["n"], 6)
        self.assertAlmostEqual(lm["power"], POWER, places=3)
        self.assertLess(lm["spread_pct"], 0.1)
        # the forecast follows the hold: laden costs more than empty
        fs.level, fs.cargo = 64.0, 1200.0
        laden = fs.cost_of(20.0)
        fs.cargo = 0.0
        empty = fs.cost_of(20.0)
        self.assertAlmostEqual(laden, burn(20.0, 1857.0 + 64.0 + 1200.0), delta=laden * 0.01)
        self.assertAlmostEqual(empty, burn(20.0, 1857.0 + 64.0), delta=empty * 0.01)
        # the old curve over the distance alone, on the same jumps
        # (the measured Panther Mk II: power 0.94, implausible - or a wide scatter)
        old = ds.FuelState(jumps=[j[:2] for j in fs.jumps])._fit_full()
        self.assertTrue(old is None or old[3] > 0.10)

    def test_prior_below_four_jumps(self):
        """Up to three jumps the power is the FSD's; the scaling uses the mass."""
        fs = ds.FuelState()
        fs.feed(loadout(), "Cmdr")
        fly(fs, [20.0])
        lm = fs.learned()
        self.assertEqual((lm["source"], lm["power"], lm["n"]), ("prior", 2.75, 1))
        fs.level, fs.cargo = 64.0, 0.0
        self.assertAlmostEqual(fs.cost_of(25.0), burn(25.0, 1857.0 + 64.0), delta=0.01 * burn(25.0, 1921.0))
        self.assertIn("1 of 4 jumps to learn", fs.summary())

    def test_learnt_per_mass_step(self):
        """A refit that changes the unladen mass by 50 t or more is another
        history; LoadGame of the same ship keeps the step."""
        fs = ds.FuelState()
        fs.feed(loadout(unladen=1857.0), "Cmdr")
        fly(fs, [20.0, 22.0, 24.0, 26.0])
        first = fs.ship
        self.assertEqual(len(fs.jumps), 4)
        fs.feed({"event": "LoadGame", "ShipID": 9}, "Cmdr")
        self.assertEqual((fs.ship, len(fs.jumps)), (first, 4))
        fs.feed(loadout(unladen=1757.0), "Cmdr")
        self.assertNotEqual(fs.ship, first)
        self.assertEqual(fs.jumps, [])
        fs.feed(loadout(unladen=1861.0), "Cmdr")             # back, within the step
        self.assertEqual((fs.ship, len(fs.jumps)), (first, 4))
        fs.feed(loadout(ship_id=3), "Other")                  # another commander's ship
        self.assertEqual(fs.jumps, [])

    def test_reset(self):
        """Reset forgets the ship's jumps; read again, the older ones stay out."""
        fs = ds.FuelState()
        fs.feed(loadout(), "Cmdr")
        for i, d in enumerate([20.0, 22.0, 24.0, 26.0]):
            fs.feed({"event": "FSDJump", "JumpDist": d, "FuelUsed": burn(d, 1921.0), "FuelLevel": 60.0},
                    ts=1000.0 + i)
        self.assertEqual(fs.learned()["n"], 4)
        fs.reset(2000.0)
        self.assertEqual(fs.learned(), {"source": "none", "power": 2.75, "mass": False,
                                        "spread_pct": None, "n": 0})
        self.assertFalse(fs.feed({"event": "FSDJump", "JumpDist": 20.0, "FuelUsed": 1.0, "FuelLevel": 60.0},
                                 ts=1500.0))
        self.assertTrue(fs.feed({"event": "FSDJump", "JumpDist": 20.0, "FuelUsed": 1.0, "FuelLevel": 60.0},
                                ts=2500.0))

    def test_old_data_without_mass(self):
        """Jumps without a Loadout mass: the curve over the distance, as up to 4.12."""
        jumps = [(d, 0.01 * d ** 2.6) for d in (10.0, 20.0, 30.0, 40.0, 50.0)]
        fs = ds.FuelState(capacity=32.0, level=32.0, max_jump=50.0, jumps=jumps)
        lm = fs.learned()
        self.assertEqual((lm["source"], lm["mass"]), ("fit", False))
        self.assertAlmostEqual(fs.cost_of(25.0), 0.01 * 25.0 ** 2.6, places=6)
        self.assertIn("learned from 5 jumps", fs.summary())


if __name__ == "__main__":
    unittest.main(verbosity=2)
