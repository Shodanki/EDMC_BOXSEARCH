# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""TIME PER SYSTEM (own-4): time and work per system against the route's
first estimate after the FSS."""

import os
import sqlite3
import tempfile
import unittest

from fis import systime
from fis.data import Database


def _ts(m):
    return "2026-11-17T%02d:%02d:00Z" % (10 + m // 60, m % 60)


def _e(m, ev, **kw):
    return dict({"timestamp": _ts(m), "event": ev}, **kw)


EVS = [
    _e(0, "FSDJump", SystemAddress=1, StarSystem="Pass"),
    _e(1, "FSDJump", SystemAddress=2, StarSystem="Work"),
    _e(2, "FSSDiscoveryScan"),
    _e(3, "Scan", ScanType="Detailed", BodyID=1), _e(3, "Scan", ScanType="Detailed", BodyID=1),
    _e(10, "SAAScanComplete", BodyID=1),
    _e(20, "Touchdown"), _e(25, "ScanOrganic", ScanType="Analyse"),
    _e(31, "Music"),                                          # then 59 min away from the keys
    _e(90, "Music"), _e(100, "SAAScanComplete", BodyID=2),    # the time runs on in the same system
    _e(101, "FSDJump", SystemAddress=3, StarSystem="Short"),
    _e(102, "Shutdown"),
    _e(200, "Location", SystemAddress=2, StarSystem="Work"),  # back in Work later
    _e(210, "ScanOrganic", ScanType="Analyse"),
]


class SysTimeTest(unittest.TestCase):
    def test_visits(self):
        v = systime.visits(EVS)
        w = v[2]
        # 1 -> 31 (30 min), pause, 90 -> 100 (10; the jump at 101 is the next system), back 200 -> 210 (10)
        self.assertEqual(w["seconds"], (30 + 10 + 10) * 60)
        self.assertEqual((w["visits"], w["honk"], len(w["scans"]), w["maps"], w["bio"], w["landings"]),
                         (2, 1, 1, 2, 2, 1))
        self.assertEqual(v[1]["seconds"], 0)          # only the arrival there, then the next jump

    def test_card_with_estimate(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "p.sqlite")
            cx = sqlite3.connect(path)
            cx.execute("CREATE TABLE route_estimates (fid TEXT, sys_id64 INTEGER, ts TEXT, total_s REAL, "
                       "travel_s REAL, work_s REAL, stops INTEGER)")
            cx.execute("INSERT INTO route_estimates VALUES ('F1', 2, '2026-11-17T10:02:00Z', 1700, 800, 900, 4)")
            cx.commit()
            cx.close()
            db = Database(path)
            out = systime.build(EVS, db, "F1")
            self.assertEqual([r["name"] for r in out["systems"]], ["Work"])       # passing through left out
            w = out["systems"][0]
            self.assertEqual((w["minutes"], w["estimate"], w["stops"], w["ratio"]), (50.0, 28.3, 4, 1.76))
            self.assertEqual((out["n"], out["ratio"], out["ratio_n"]), (1, 1.76, 1))
            self.assertIsNone(systime.build(EVS, db, "F2")["ratio"])                 # another commander's

    def test_without_the_table(self):
        # a plugin database from before 5.0: no estimates, no error
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "old.sqlite")
            sqlite3.connect(path).close()
            out = systime.build(EVS, Database(path), "F1")
            self.assertIsNone(out["systems"][0]["estimate"])


if __name__ == "__main__":
    unittest.main()
