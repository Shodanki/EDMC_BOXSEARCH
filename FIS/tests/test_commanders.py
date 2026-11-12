# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""C1: two commanders on one PC - exploration per commander, knowledge shared,
the survey for the main commander, the setting in fis.ini."""

import os
import sqlite3
import tempfile
import unittest

from fis.config import Config
from fis.data import CMDR_READY, MAIN, Database

from tests import fixtures as fx

MAIN_FID, SECOND = "F100", "F200"


def add_commanders(path, ready=True):
    """The plugin 4.8 tables: F100 (carrier) explored planet 1, F200 only
    arrived in the test system."""
    import sysdb                       # the plugin's schema (fixtures put it on sys.path)
    cx = sqlite3.connect(path)
    cx.executescript(sysdb.SCHEMA)
    cx.executemany("INSERT INTO commanders(fid,name,carrier,first_seen,last_seen) VALUES (?,?,?,?,?)",
                   [(MAIN_FID, "Main", 1, "2026-01-01T00:00:00Z", "2026-11-01T00:00:00Z"),
                    (SECOND, "Second", 0, "2026-02-01T00:00:00Z", "2026-11-02T00:00:00Z")])
    cx.executemany("INSERT INTO cmdr_logins VALUES (?,?)",
                   [(SECOND, "2026-11-0%dT00:00:00Z" % i) for i in range(1, 5)])
    cx.executemany("INSERT INTO cmdr_systems(fid,sys_id64,visited_ts,fss_complete) VALUES (?,?,?,?)",
                   [(MAIN_FID, fx.SYS_ID, "2026-11-04T20:00:00Z", 1),
                    (SECOND, fx.SYS_ID, "2026-11-05T20:00:00Z", 0)])
    cx.executemany("INSERT INTO cmdr_bodies(fid,sys_id64,body_id,scanned,mapped,was_discovered) "
                   "VALUES (?,?,?,?,?,?)",
                   [(MAIN_FID, fx.SYS_ID, b, 1, 1 if b == 1 else 0, 0 if b < 2 else 1)
                    for b in (0, 1, 2, 3)])
    if ready:
        cx.execute("INSERT INTO meta VALUES (?, '2026-11-11T00:00:00Z')", (CMDR_READY,))
    cx.commit()
    cx.close()


class _Base(unittest.TestCase):
    ready = True

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="fis-test-")
        cls.db_path = fx.make_db(os.path.join(cls.tmp, "db.sqlite"))
        cfg = Config()
        cfg.plugin_dir = fx.PLUGIN_DIR
        cfg.use_plugin_path()
        add_commanders(cls.db_path, cls.ready)
        from fis import model
        cls.model = model

    def setUp(self):
        self.db = Database(self.db_path)


class TestPerCommander(_Base):
    def body(self, s, bid):
        return next(b for b in s["bodies"] if b["body_id"] == bid)

    def test_suggestion_and_main(self):
        self.assertEqual(self.db.suggest_main(), MAIN_FID)        # carrier beats sessions
        self.assertEqual(self.db.main_fid(), MAIN_FID)
        self.db.main_setting = SECOND                              # FIS setting wins
        self.assertEqual(self.db.view_fid(MAIN), SECOND)

    def test_system_per_commander(self):
        main = self.model.build_system(self.db, fx.SYS_ID, None, ["todo"], fid=MAIN_FID)
        sec = self.model.build_system(self.db, fx.SYS_ID, None, ["todo"], fid=SECOND)
        self.assertTrue(self.body(main, 1)["flags"]["mapped"])
        self.assertFalse(self.body(sec, 1)["flags"]["mapped"])
        self.assertTrue(main["fss_complete"])
        self.assertFalse(sec["fss_complete"])
        self.assertEqual(sec["also_by"], ["Main"])
        self.assertEqual(main["also_by"], ["Second"])
        # knowledge is shared: the class and the bio signals are there for both
        self.assertEqual(self.body(sec, 1)["flags"]["bio"], 2)
        self.assertEqual(self.body(sec, 1)["cls"], self.body(main, 1)["cls"])
        # the second commander still has the planet to map
        self.assertIn(1, [leg["body_id"] for leg in sec["route"]["legs"]])

    def test_survey_for_main_commander(self):
        sv = self.model.build_survey(self.db)
        self.assertEqual(sv["commander"], "Main")
        self.assertEqual(sv["systems"]["fss_complete"], 1)
        self.assertEqual(sv["also_by"], [{"name": "Second", "visited": 1}])
        self.db.main_setting = SECOND
        self.assertEqual(self.model.build_survey(self.db)["systems"]["fss_complete"], 0)

    def test_r3_route_starts_at_the_carrier(self):
        cx = sqlite3.connect(self.db_path)
        cx.execute("UPDATE cmdr_systems SET start_body=3, start_name=? WHERE fid=?",
                   (fx.SYS + " 2", SECOND))
        cx.commit()
        cx.close()
        try:
            sec = self.model.build_system(self.db, fx.SYS_ID, None, ["all"], fid=SECOND)
            main = self.model.build_system(self.db, fx.SYS_ID, None, ["all"], fid=MAIN_FID)
        finally:
            cx = sqlite3.connect(self.db_path)
            cx.execute("UPDATE cmdr_systems SET start_body=NULL, start_name=NULL")
            cx.commit()
            cx.close()
        r = sec["route"]
        self.assertEqual(r["start"]["body_id"], 3)
        self.assertEqual(r["start"]["short"], "2")
        gas = self.body(sec, 3)
        self.assertEqual(r["legs"][0]["from"], gas["pos"])          # from the carrier, not (0,0,0)
        self.assertNotIn(0, [leg["body_id"] for leg in r["legs"]])  # arrival star left out
        self.assertIsNone(main["route"]["start"])                   # the other commander: main star
        self.assertIn(0, [leg["body_id"] for leg in main["route"]["legs"]])

    def test_lost_in_a_crash_is_marked(self):
        cx = sqlite3.connect(self.db_path)
        cx.execute("UPDATE cmdr_bodies SET mapped=0, lost_what=?, lost_ts='2026-11-11T19:27:41Z' "
                   "WHERE fid=? AND body_id=1", ('["bio:Bacterium Cerbrus", "map"]', MAIN_FID))
        cx.commit()
        cx.close()
        try:
            s = self.model.build_system(self.db, fx.SYS_ID, None, ["todo"], fid=MAIN_FID)
            lost = self.db.lost_summary(MAIN_FID)
        finally:
            cx = sqlite3.connect(self.db_path)
            cx.execute("UPDATE cmdr_bodies SET mapped=1, lost_what=NULL, lost_ts=NULL WHERE body_id=1")
            cx.commit()
            cx.close()
        self.assertEqual(self.body(s, 1)["flags"]["lost"], ["bio:Bacterium Cerbrus", "map"])
        self.assertEqual(s["lost"], {"bodies": 1, "scan": 0, "map": 1, "bio": ["Bacterium Cerbrus"]})
        self.assertTrue(any(leg["lost"] for leg in s["route"]["legs"] if leg["body_id"] == 1))
        self.assertEqual((lost[0]["name"], lost[0]["map"], lost[0]["bio"]), (fx.SYS, 1, ["Bacterium Cerbrus"]))

    def test_lost_in_the_briefing(self):
        cx = sqlite3.connect(self.db_path)
        cx.execute("UPDATE cmdr_bodies SET lost_what=?, lost_ts='2026-11-11T19:27:41Z' "
                   "WHERE fid=? AND body_id=1", ('["map"]', MAIN_FID))
        cx.commit()
        cx.close()
        try:
            live = {"target": {"name": fx.SYS, "id64": fx.SYS_ID, "source": "fsdtarget"}}
            b = self.model.build_briefing(self.db, live, fid=MAIN_FID)
            other = self.model.build_briefing(self.db, live, fid=SECOND)
        finally:
            cx = sqlite3.connect(self.db_path)
            cx.execute("UPDATE cmdr_bodies SET lost_what=NULL, lost_ts=NULL")
            cx.commit()
            cx.close()
        self.assertTrue(b["target"]["visited"])
        self.assertEqual(b["target"]["lost"]["map"], 1)
        self.assertIsNone(other["target"]["lost"])          # the other commander lost nothing

    def test_briefing_visited_and_also(self):
        live = {"target": {"name": fx.SYS, "id64": fx.SYS_ID, "source": "fsdtarget"}}
        b = self.model.build_briefing(self.db, live, fid=SECOND)
        self.assertTrue(b["target"]["visited"])
        self.assertEqual(b["target"]["also_by"], ["Main"])


class TestNotReplayedYet(_Base):
    ready = False

    def test_shared_view_until_the_plugin_replayed(self):
        sec = self.model.build_system(Database(self.db_path), fx.SYS_ID, None, ["todo"], fid=SECOND)
        b1 = next(b for b in sec["bodies"] if b["body_id"] == 1)
        self.assertEqual(b1["flags"]["first"], True)        # the shared columns, as up to 4.7
        self.assertEqual(Database(self.db_path).view_fid(MAIN), None)


class TestSetting(unittest.TestCase):
    def test_main_cmdr_in_fis_ini(self):
        path = os.path.join(tempfile.mkdtemp(prefix="fis-test-"), "fis.ini")
        c = Config()
        c.ini_path = path
        c.main_cmdr = SECOND
        c.save()
        self.assertEqual(Config().load(path).main_cmdr, SECOND)


if __name__ == "__main__":
    unittest.main()
