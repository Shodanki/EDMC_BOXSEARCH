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
