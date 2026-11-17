# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
Resetting a learnt model (SK3, 5.0): the marks in FIS/learn_reset.json and
what the plugin leaves out at start-up because of them - the work replay
from the reset on, the fuel model of one ship.

    python tests/learn_reset.py      (from the plugin folder)
"""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import deepspace as ds  # noqa: E402
import journalscan as js  # noqa: E402
import learnreset as lr  # noqa: E402


def _ts(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


class LearnReset(unittest.TestCase):
    """learnreset and the replays that honour it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, lr.FILE_NAME)

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_and_broken_file(self):
        """No file or a broken one: nothing was reset."""
        self.assertEqual(lr.load(self.path), {"version": 1, "route": None, "work": None, "value": None, "fuel": {}})
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        self.assertIsNone(lr.since(lr.load(self.path), "route"))
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"route": "yesterday", "fuel": {"x": "y"}}, fh)
        self.assertEqual(lr.load(self.path), {"version": 1, "route": None, "work": None, "value": None, "fuel": {}})
        self.assertEqual(lr.plugin_path("P"), os.path.join("P", "FIS", "learn_reset.json"))

    def test_marks(self):
        """A mark per model, the fuel mark per ship; the file is replaced whole."""
        lr.mark(self.path, "route", 100.0)
        lr.mark(self.path, "value", 150.0)                     # B6: the exploration values
        lr.mark(self.path, "fuel", 200.0, ship=("Cmdr", 9, 37))
        lr.mark(self.path, "fuel", 300.0, ship=("Cmdr", 3, 33))
        got = lr.load(self.path)
        self.assertEqual((lr.since(got, "route"), lr.since(got, "work"), lr.since(got, "value")), (100.0, None, 150.0))
        self.assertEqual(lr.fuel_since(got), {("Cmdr", 9, 37): 200.0, ("Cmdr", 3, 33): 300.0})
        self.assertFalse(os.path.exists(self.path + ".tmp"))
        with self.assertRaises(ValueError):
            lr.mark(self.path, "everything", 1.0)
        with self.assertRaises(ValueError):
            lr.mark(self.path, "fuel", 1.0)

    def test_work_replay_from_the_reset(self):
        """A surface scan before the reset is not measured, one after it is."""
        t0 = 1_800_000_000
        ev = []
        for base in (t0, t0 + 10_000):
            ev += [{"timestamp": _ts(base), "event": "FSDJump", "SystemAddress": 1, "StarSystem": "A"},
                   {"timestamp": _ts(base + 100), "event": "SupercruiseExit", "SystemAddress": 1,
                    "Body": "A 1", "BodyID": 1},
                   {"timestamp": _ts(base + 190), "event": "SAAScanComplete", "SystemAddress": 1,
                    "BodyName": "A 1", "BodyID": 1}]
        f = os.path.join(self.tmp.name, "Journal.2027-01-15T080000.01.log")
        with open(f, "w", encoding="utf-8") as fh:
            fh.write("\n".join(json.dumps(e) for e in ev) + "\n")
        self.assertEqual(len(js.replay_work([f]).dss), 2)
        self.assertEqual(js.replay_work([f], since=t0 + 5_000).dss, [90.0])

    def test_fuel_reset_per_ship_survives_a_replay(self):
        """The marks set FuelState.since: the ship's older jumps stay out,
        another ship keeps its own."""
        lr.mark(self.path, "fuel", 1_000.0, ship=("Cmdr", 9, 37))
        fs = ds.FuelState()
        fs.since = lr.fuel_since(lr.load(self.path))
        load = {"event": "Loadout", "ShipID": 9, "UnladenMass": 1857.0, "FuelCapacity": {"Main": 64.0}}
        fs.feed(load, "Cmdr")
        self.assertEqual(fs.ship, ("Cmdr", 9, 37))
        jump = {"event": "FSDJump", "JumpDist": 20.0, "FuelUsed": 4.0, "FuelLevel": 60.0}
        self.assertFalse(fs.feed(jump, ts=999.0))
        self.assertTrue(fs.feed(jump, ts=1_001.0))
        fs.feed(dict(load, ShipID=3, UnladenMass=1650.0), "Cmdr")
        self.assertTrue(fs.feed(jump, ts=10.0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
