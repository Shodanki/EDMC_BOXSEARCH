# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""FX3: STATISTICS > LEARNING STATUS shows the plugin's find predictions
(find_log) against what the scans showed - and nothing when the plugin or
the table is missing."""

import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

from fis import learn
from fis.data import Database
from tests.fixtures import PLUGIN_DIR, make_db


class FindOddsTest(unittest.TestCase):
    def setUp(self):
        if PLUGIN_DIR not in sys.path:          # as Config.use_plugin_path does
            sys.path.append(PLUGIN_DIR)
        self.path = make_db(os.path.join(tempfile.mkdtemp(), "t.sqlite"))
        cx = sqlite3.connect(self.path)
        cx.executescript("""
            CREATE TABLE IF NOT EXISTS cmdr_systems (fid TEXT, sys_id64 INTEGER, visited_ts TEXT,
              fss_complete INTEGER DEFAULT 0, arrival_ts TEXT, start_body INTEGER, start_name TEXT, lost_ts TEXT);
            CREATE TABLE IF NOT EXISTS cmdr_bodies (fid TEXT, sys_id64 INTEGER, body_id INTEGER,
              scanned INTEGER DEFAULT 0, mapped INTEGER DEFAULT 0, was_discovered INTEGER);
            CREATE TABLE find_log (fid TEXT, sys_id64 INTEGER, ts TEXT, name TEXT, kind TEXT, star TEXT,
              level TEXT, height TEXT, p REAL, low REAL, high REAL, n INTEGER);
            INSERT INTO systems (name, id64, x, y, z, star_class) VALUES
              ('Synuefe WD-G b44-0', 9101, 500, -140, -115, 'M'), ('Synuefe GV-D b45-4', 9102, 505, -200, -103, 'M');
            INSERT INTO cmdr_systems (fid, sys_id64, fss_complete) VALUES ('F1', 9101, 1), ('F1', 9102, 0);
            INSERT INTO cmdr_bodies (fid, sys_id64, body_id, scanned, was_discovered) VALUES
              ('F1', 9101, 0, 1, 1), ('F1', 9101, 1, 1, 0), ('F1', 9102, 0, 1, 1);
            INSERT INTO find_log VALUES ('F1', 9101, 't', 'Synuefe WD-G b44-0', 'b', 'M', 'unchecked', 'high',
              0.08, 0.01, 0.4, 0), ('F1', 9102, 't', 'Synuefe GV-D b45-4', 'b', 'M', 'unchecked', 'high',
              0.2, 0.05, 0.5, 1);
        """)
        cx.commit()
        cx.close()
        self.db = Database(self.path)

    def test_calibration(self):
        f = learn.find_odds(self.db)
        self.assertIsNotNone(f)
        self.assertEqual((f["logged"], f["waiting"], f["learnt"]), (2, 1, 1))
        b = f["bands"][1]
        self.assertEqual((b["n"], b["hits"]), (1, 1))
        self.assertEqual(f["base"]["pg"], {"n": 1, "hits": 1})

    def test_missing(self):
        with mock.patch("fis.model.plugin", return_value=type("P", (), {"findodds": None})()):
            self.assertIsNone(learn.find_odds(self.db))
        cx = sqlite3.connect(self.path)
        cx.execute("DROP TABLE find_log")
        cx.commit()
        cx.close()
        f = learn.find_odds(self.db)
        if f is not None:
            self.assertEqual(f["logged"], 0)

    def test_target_odds(self):
        """FX5: BRIEFING and GALAXY get the chance of a find, counted once a minute."""
        learn._odds_cache.update(t=0.0, db=None, m=None)
        o = learn.target_odds(self.db, "Synuefe XT-Q c21-13", "K", "known", -150.0, now=1000.0)
        self.assertIsNotNone(o)
        self.assertEqual(o["learnt"], 1)
        self.assertTrue(o["low"] <= o["p"] <= o["high"])
        self.assertEqual(o["why"], "pg/high")          # the one settled visit lies off the plane
        m = learn._odds_cache["m"]
        learn.target_odds(self.db, "Synuefe XT-Q c21-13", "K", "known", -150.0, now=1030.0)
        self.assertIs(learn._odds_cache["m"], m)       # within a minute: not counted again
        learn.target_odds(self.db, "Synuefe XT-Q c21-13", "K", "known", -150.0, now=1100.0)
        self.assertIsNot(learn._odds_cache["m"], m)
        self.assertIsNone(learn.target_odds(self.db, None, None, None, None))
        with mock.patch("fis.model.plugin", return_value=type("P", (), {"findodds": None})()):
            self.assertIsNone(learn.target_odds(self.db, "Synuefe XT-Q c21-13", "K", "known", 0.0))


if __name__ == "__main__":
    unittest.main()
