"""GALAXY: flight path per commander, carrier path, boxel status in a sphere."""

import os
import sqlite3
import tempfile
import unittest

from tests import fixtures as fx
from tests.test_fleet import _write_journals

from fis import fleet as fl
from fis.config import Config
from fis.data import Database


class GalaxyTest(unittest.TestCase):
    def setUp(self):
        cfg = Config()
        cfg.plugin_dir = fx.PLUGIN_DIR
        cfg.use_plugin_path()
        from fis import galaxy
        self.galaxy = galaxy
        self.tmp = tempfile.TemporaryDirectory()
        _write_journals(self.tmp.name)
        self.ar = fl.Archive(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_path_of_logged_in_commander(self):
        path = self.galaxy.flight_path(self.ar)
        names = [p["name"] for p in path]
        self.assertEqual(names, ["Alpha", "Beta"])          # the other commander flew nowhere here
        self.assertEqual(path[1]["kind"], "jump")
        car = self.galaxy.carrier_path(self.ar)
        self.assertEqual([c["name"] for c in car], ["Alpha", "Beta"])
        self.assertEqual(car[1]["x"], 400)
        now = self.galaxy.carrier_now(self.ar)
        self.assertEqual(now["system"], "Beta")
        self.assertEqual(now["name"], "TESTCARRIER")
        self.assertFalse(now["expected"])
        self.assertNotIn("jump", now)

    def test_carrier_jump_pending_and_expected(self):
        from fis.live import parse_ts
        with open(os.path.join(self.tmp.name, "Journal.2026-01-30T090000.01.log"), "w", encoding="utf-8") as fh:
            fh.write('{"timestamp":"2026-01-30T09:00:00Z","event":"CarrierJumpRequest","SystemName":"Alpha",'
                     '"SystemAddress":1,"BodyID":3,"DepartureTime":"2026-01-30T09:15:00Z"}\n')
        ar = fl.Archive(self.tmp.name)
        dep = parse_ts("2026-01-30T09:15:00Z")
        before = self.galaxy.carrier_now(ar, now=dep - 60)
        self.assertEqual(before["system"], "Beta")           # still there, jump to come
        self.assertEqual(before["jump"]["to"], "Alpha")
        self.assertEqual(before["jump"]["body_id"], 3)
        self.assertEqual(before["jump"]["x"], 0)
        after = self.galaxy.carrier_now(ar, now=dep + 3600)
        self.assertEqual(after["system"], "Alpha")           # not seen, but departed an hour ago
        self.assertTrue(after["expected"])
        self.assertEqual(after["body_id"], 3)
        self.assertNotIn("jump", after)

    def test_boxels_in_sphere(self):
        path = os.path.join(self.tmp.name, "db.sqlite")
        cx = sqlite3.connect(path)
        cx.executescript("""
        CREATE TABLE systems (name TEXT, id64 INTEGER, x REAL, y REAL, z REAL, quality INTEGER,
            source TEXT, sources TEXT, star_class TEXT, visited INTEGER, visited_ts TEXT,
            body_count INTEGER, nonbody_count INTEGER, fss_complete INTEGER, first_seen TEXT, updated TEXT);
        CREATE TABLE boxels (key TEXT, sector TEXT, mc INTEGER, n2_max INTEGER, n2_end INTEGER,
            complete INTEGER, updated TEXT);
        CREATE TABLE survey (id INTEGER, active INTEGER, start_system TEXT, cx REAL, cy REAL, cz REAL,
            radius REAL, masscodes TEXT, started TEXT, updated TEXT);
        CREATE TABLE spheres (id INTEGER, label TEXT, cx REAL, cy REAL, cz REAL, radius REAL,
            origin TEXT, started TEXT, closed TEXT);
        """)
        # two systems of one 20 ly boxel ("b") near Sol; that boxel is closed
        cx.execute("INSERT INTO systems(name,x,y,z,visited) VALUES ('Synuefe AB-C b1-2', 5, 5, 5, 1)")
        cx.execute("INSERT INTO boxels VALUES ('Synuefe AB-C b1', 'Synuefe', 1, 2, NULL, 1, '')")
        cx.execute("INSERT INTO survey VALUES (1, 1, 'Start', 0, 0, 0, 30, '1', '', '')")
        cx.execute("INSERT INTO spheres VALUES (1, 'Start', 0, 0, 0, 30, 'free', '', NULL)")
        cx.commit()
        cx.close()
        g = self.galaxy.build_galaxy(Database(path), self.ar, {"system": {"pos": [1, 2, 3], "name": "X"}})
        self.assertEqual(g["mc"], 1)
        self.assertEqual(g["boxel_size"], 20.0)
        st = {b["status"] for b in g["boxels"]}
        self.assertIn("closed", st)
        self.assertIn("unchecked", st)
        closed = [b for b in g["boxels"] if b["status"] == "closed"]
        self.assertEqual(closed[0]["key"], "Synuefe AB-C b1")
        self.assertEqual(len(g["systems"]), 1)
        self.assertEqual(g["you"]["x"], 1)
        self.assertTrue(g["you"]["live"])
        self.assertEqual(g["stats"]["jumps"], 1)
        # no live position (FIS started before the game): the last system of the log
        g = self.galaxy.build_galaxy(Database(path), self.ar, {})
        self.assertFalse(g["you"]["live"])
        self.assertEqual(g["you"]["name"], g["path"][-1]["name"])


if __name__ == "__main__":
    unittest.main()
