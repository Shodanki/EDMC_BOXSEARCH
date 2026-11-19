# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
Resetting a learnt model (SK3, 5.0): the marks in FIS/learn_reset.json and
what the plugin leaves out at start-up because of them - the work replay
from the reset on, the fuel model of one ship. SM1: a sale the game did not
log, marked as sold in the FIS, clears the commander's open data in the
plugin database once.

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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plugin_pkg  # noqa: E402
plugin_pkg.import_plugin()
from SHBOXSEARCH.sysdb import SystemDB  # noqa: E402


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
        self.assertEqual(lr.load(self.path), {"version": 1, "route": None, "work": None, "value": None, "fuel": {}, "sold": {}})
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        self.assertIsNone(lr.since(lr.load(self.path), "route"))
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"route": "yesterday", "fuel": {"x": "y"}}, fh)
        self.assertEqual(lr.load(self.path), {"version": 1, "route": None, "work": None, "value": None, "fuel": {}, "sold": {}})
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


class SoldMark(unittest.TestCase):
    """SM1 (user 19.11.2026): a carrier sale wrote no MultiSellExplorationData;
    the commander marks the data as sold."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, lr.FILE_NAME)

    def tearDown(self):
        self.tmp.cleanup()

    def test_marks_per_commander_and_cache(self):
        self.assertEqual(lr.sold_since(lr.load_cached(self.path), "F1"), {})
        lr.mark_sold(self.path, "F1", 1_000.0)
        lr.mark_sold(self.path, "F2", 2_000.0, ("explo",))
        self.assertEqual(lr.sold_since(lr.load_cached(self.path), "F1"), {"explo": 1_000.0, "bio": 1_000.0})
        self.assertEqual(lr.sold_since(lr.load(self.path), "F2"), {"explo": 2_000.0})
        self.assertEqual(lr.sold_since(lr.load(self.path), None), {})
        with self.assertRaises(ValueError):
            lr.mark_sold(self.path, "F1", 1.0, ("fuel",))
        # broken entries are dropped, the rest of the file is kept
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"route": 5.0, "sold": {"F1": {"explo": "x", "bio": 7.0}, "F3": 4}}, fh)
        got = lr.load(self.path)
        self.assertEqual((got["route"], got["sold"]), (5.0, {"F1": {"bio": 7.0}}))

    def test_plugin_db_clears_open_data_once(self):
        db = SystemDB(os.path.join(self.tmp.name, "db.sqlite"))
        try:
            db.set_commander("F1", "Main")
            db.sold_marks = lambda fid: lr.sold_since(lr.load_cached(self.path), fid)
            t0 = 1_794_000_000.0
            def scan(t, bid):       # noqa: E306
                return {"timestamp": _ts(t), "event": "Scan", "ScanType": "Detailed", "StarSystem": "Sm A",
                        "SystemAddress": 901, "BodyName": "Sm A %d" % bid, "BodyID": bid,
                        "PlanetClass": "Icy body", "DistanceFromArrivalLS": 10.0 * bid}
            db.ingest_journal_event({"timestamp": _ts(t0), "event": "FSDJump", "StarSystem": "Sm A",
                                     "SystemAddress": 901, "StarPos": [1.0, 2.0, 3.0]})
            for bid in (1, 2):
                db.ingest_journal_event(scan(t0 + bid, bid))
            db.ingest_journal_event({"timestamp": _ts(t0 + 5), "event": "SAAScanComplete", "SystemAddress": 901,
                                     "BodyName": "Sm A 2", "BodyID": 2, "ProbesUsed": 4, "EfficiencyTarget": 6})
            db.ingest_journal_event({"timestamp": _ts(t0 + 6), "event": "ScanOrganic", "ScanType": "Analyse",
                                     "SystemAddress": 901, "Body": 2, "Species_Localised": "Bacterium Tela"})
            self.assertEqual(len(db.unsold_rows("F1")), 2)
            # sold at the carrier, no sale event; the mark comes from the FIS
            lr.mark_sold(self.path, "F1", t0 + 60)
            db.ingest_journal_event(scan(t0 + 30, 3))          # before the mark: still open
            self.assertEqual(len(db.unsold_rows("F1")), 3)
            db.ingest_journal_event(scan(t0 + 120, 4))         # after it: the mark applies first
            rows = db.unsold_rows("F1")
            self.assertEqual([r["body_id"] for r in rows], [4])
            # once only: a replay of older events or a later start keeps newer data
            db.ingest_journal_event(scan(t0 + 1, 1))
            self.assertEqual(db.apply_sold_marks(), 0)
            self.assertEqual(sorted(r["body_id"] for r in db.unsold_rows("F1")), [4])
            # another commander keeps theirs; a newer mark applies by the clock
            lr.mark_sold(self.path, "F1", t0 + 200, ("explo",))
            self.assertEqual(db.apply_sold_marks(), 1)
            self.assertEqual(db.unsold_rows("F1"), [])
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
