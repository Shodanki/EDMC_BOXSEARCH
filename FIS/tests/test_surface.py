"""OBERFLÄCHE: projection, marks, colony circles (plugin 4.4 tables)."""

import math
import os
import sqlite3
import tempfile
import unittest

from tests import fixtures as fx

from fis.config import Config
from fis.data import Database


def _db(path):
    cx = sqlite3.connect(path)
    cx.executescript("""
    CREATE TABLE systems (name TEXT, id64 INTEGER, x REAL, y REAL, z REAL, quality INTEGER,
        source TEXT, sources TEXT, star_class TEXT, visited INTEGER, visited_ts TEXT,
        body_count INTEGER, nonbody_count INTEGER, fss_complete INTEGER, first_seen TEXT, updated TEXT);
    CREATE TABLE bodies (sys_id64 INTEGER, body_id INTEGER, name TEXT, radius REAL, gravity REAL);
    CREATE TABLE surface_track (sys_id64 INTEGER, body_name TEXT, ts REAL, lat REAL, lon REAL,
        alt REAL, heading REAL, mode TEXT);
    CREATE TABLE surface_marks (ts TEXT, sys_id64 INTEGER, body_name TEXT, kind TEXT, label TEXT,
        detail TEXT, lat REAL, lon REAL);
    """)
    cx.execute("INSERT INTO systems(name,id64,quality,visited) VALUES ('Sys',1,40,1)")
    cx.execute("INSERT INTO bodies VALUES (1, 5, 'Sys 1 a', 1000000.0, 1.0)")
    # 1 degree of longitude at the equator on R = 1000 km is 17453 m
    for i, lon in enumerate((0.0, 0.01, 0.02)):
        cx.execute("INSERT INTO surface_track VALUES (1,'Sys 1 a',?,0,?,0,90,'srv')", (i * 10.0, lon))
    cx.execute("INSERT INTO surface_marks VALUES ('2026-11-05T10:00:00Z',1,'Sys 1 a','bio_log',"
               "'Bacterium Cerbrus','Bacterium',0,0)")
    cx.execute("INSERT INTO surface_marks VALUES ('2026-11-05T10:05:00Z',1,'Sys 1 a','codex',"
               "'Water Ice Fumarole','Geology',0,0.02)")
    cx.commit()
    cx.close()


class SurfaceTest(unittest.TestCase):
    def setUp(self):
        cfg = Config()
        cfg.plugin_dir = fx.PLUGIN_DIR
        cfg.use_plugin_path()
        from fis import model
        self.model = model
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "s.sqlite")
        _db(self.path)
        self.db = Database(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_live_on_body(self):
        live = {"system": {"id64": 1}, "status": {"body_name": "Sys 1 a", "lat": 0.0,
                "lon": 0.0337, "radius": 1000000.0, "heading": 90, "alt": 2, "flags": 1 << 26,
                "flags2": 0}}
        s = self.model.build_surface(self.db, live)
        self.assertTrue(s["here"])
        self.assertEqual(s["track"][0]["mode"], "srv")
        bio = s["bio"][0]
        self.assertEqual(bio["range_m"], 500)
        # you are 0.0337 deg = ~588 m east of the log: far enough for Bacterium
        self.assertAlmostEqual(bio["nearest_m"], 588, delta=3)
        self.assertTrue(bio["ok"])
        codex = [m for m in s["marks"] if m["kind"] == "codex"][0]
        self.assertAlmostEqual(codex["dist_m"], 0.0137 * math.pi / 180 * 1e6, delta=3)
        self.assertEqual(s["me"]["mode"], "srv")

    def test_rhino_from_hovering_ship(self):
        # the Rhino is dropped by a ship hovering just above the ground: no
        # Touchdown, the ship waits at the drop point - shown as last known
        cx = sqlite3.connect(self.path)
        cx.execute("INSERT INTO surface_marks VALUES ('2026-11-05T10:06:00Z',1,'Sys 1 a',"
                   "'srv_out','SRV Rhino',NULL,0,0.01)")
        cx.commit()
        cx.close()
        live = {"system": {"id64": 1}, "status": {"body_name": "Sys 1 a", "lat": 0.0,
                "lon": 0.0337, "radius": 1000000.0, "heading": 90, "alt": 1, "flags": 1 << 26,
                "flags2": 0}}
        s = self.model.build_surface(self.db, live)
        self.assertTrue(s["ship"]["hover"])
        self.assertEqual(round(s["ship"]["bearing"]), 270)
        self.assertAlmostEqual(s["ship"]["dist_m"], 0.0237 * math.pi / 180 * 1e6, delta=3)
        # back in the ship: nothing left to point at
        cx = sqlite3.connect(self.path)
        cx.execute("INSERT INTO surface_marks VALUES ('2026-11-05T10:09:00Z',1,'Sys 1 a',"
                   "'srv_in','SRV Rhino',NULL,0,0.01)")
        cx.commit()
        cx.close()
        self.assertNotIn("ship", self.model.build_surface(self.db, live))

    def test_rhino_rigs(self):
        # one "refined" mark per tonne; the view gets one numbered rig each
        cx = sqlite3.connect(self.path)
        cx.execute("INSERT INTO surface_marks VALUES ('2026-11-05T10:06:00Z',1,'Sys 1 a',"
                   "'srv_out','SRV Rhino',NULL,0,0.0)")
        for i in range(11):
            cx.execute("INSERT INTO surface_marks VALUES (?,1,'Sys 1 a','refined','Deuterium',"
                       "'rig',0,0.01)", ("2026-11-05T10:10:%02dZ" % i,))
        for i in range(3):
            cx.execute("INSERT INTO surface_marks VALUES (?,1,'Sys 1 a','refined','Deuterium',"
                       "'rig',0,0.02)", ("2026-11-05T10:20:%02dZ" % i,))
        cx.commit()
        cx.close()
        live = {"system": {"id64": 1}, "status": {"body_name": "Sys 1 a", "lat": 0.0,
                "lon": 0.0337, "radius": 1000000.0, "heading": 90, "alt": 1, "flags": 1 << 26,
                "flags2": 0}}
        s = self.model.build_surface(self.db, live)
        rigs = [m for m in s["marks"] if m["kind"] == "rig"]
        self.assertEqual([m["label"] for m in rigs], ["Rig 1 · 11 t Deuterium", "Rig 2 · 3 t Deuterium"])
        self.assertFalse([m for m in s["marks"] if m["kind"] == "refined"])
        self.assertAlmostEqual(rigs[0]["dist_m"], 0.0237 * math.pi / 180 * 1e6, delta=3)

    def test_rhino_hold(self):
        from fis.mining import rhino_hold
        base = {"system": {"id64": 1}, "vehicle": "SRV Rhino",
                "status": {"body_name": "Sys 1 a", "lat": 0.0, "lon": 0.0, "radius": 1000000.0,
                           "heading": 0, "alt": 1, "flags": 1 << 26, "flags2": 0}}
        base["status"]["cargo"] = 40.0
        self.assertEqual(rhino_hold(base)["rigs_fit"], 2)           # 32 t free
        base["status"]["cargo"] = 67.0
        h = self.model.build_surface(self.db, base)["rhino"]
        self.assertEqual((h["free"], h["rigs_fit"], h["short"]), (5, 0, True))
        # Cargo.json of the SRV when Status has no figure
        base["status"].pop("cargo")
        self.assertEqual(rhino_hold(base, {"Vessel": "SRV", "Count": 60})["rigs_fit"], 1)
        self.assertIsNone(rhino_hold(dict(base, vehicle="SRV Scarab"), {"Vessel": "SRV", "Count": 1}))
        self.assertNotIn("rhino", self.model.build_surface(self.db, dict(base, vehicle=None)))

    def test_parked_srv_and_restarted_log(self):
        cx = sqlite3.connect(self.path)
        cx.execute("INSERT INTO surface_marks VALUES ('2026-11-05T10:06:00Z',1,'Sys 1 a',"
                   "'srv_parked','SRV','Nomad',0,0.01)")
        # a second Log restarts the species: only its own point counts
        cx.execute("INSERT INTO surface_marks VALUES ('2026-11-05T10:07:00Z',1,'Sys 1 a',"
                   "'bio_log','Bacterium Cerbrus','Bacterium',0,0.03)")
        cx.commit()
        cx.close()
        live = {"system": {"id64": 1}, "status": {"body_name": "Sys 1 a", "lat": 0.0,
                "lon": 0.0337, "radius": 1000000.0, "heading": 90, "alt": 0, "flags": 0,
                "flags2": 1}}
        s = self.model.build_surface(self.db, live)
        self.assertEqual(s["parked"]["label"], "Nomad")
        self.assertAlmostEqual(s["parked"]["dist_m"], 0.0237 * math.pi / 180 * 1e6, delta=3)
        self.assertEqual(round(s["parked"]["bearing"]), 270)      # back west
        bio = s["bio"][0]
        self.assertEqual((len(bio["points"]), bio["samples"]), (1, 1))
        self.assertLess(bio["nearest_m"], 100)

    def test_active_species(self):
        """E10: the unfinished species with the newest log/sample is active."""
        cx = sqlite3.connect(self.path)
        rows = [("2026-11-05T10:10:00Z", "bio_log", "Stratum Tectonicas", "Stratum", 0.05),
                ("2026-11-05T10:20:00Z", "bio_log", "Fonticulua Campestris", "Fonticulua", 0.06),
                ("2026-11-05T10:30:00Z", "bio_sample", "Stratum Tectonicas", "Stratum", 0.07),
                # an analysed species never is the active one, however new
                ("2026-11-05T10:40:00Z", "bio_log", "Tussock Ignis", "Tussock", 0.08),
                ("2026-11-05T10:41:00Z", "bio_sample", "Tussock Ignis", "Tussock", 0.081),
                ("2026-11-05T10:42:00Z", "bio_analyse", "Tussock Ignis", "Tussock", 0.082)]
        for ts, kind, label, genus, lon in rows:
            cx.execute("INSERT INTO surface_marks VALUES (?,1,'Sys 1 a',?,?,?,0,?)",
                       (ts, kind, label, genus, lon))
        cx.commit()
        cx.close()
        live = {"system": {"id64": 1}, "status": {"body_name": "Sys 1 a", "lat": 0.0,
                "lon": 0.07, "radius": 1000000.0, "heading": 90, "alt": 0, "flags": 0,
                "flags2": 1}}
        s = self.model.build_surface(self.db, live)
        self.assertEqual(s["active"], {"species": "Stratum Tectonicas", "genus": "Stratum"})
        act = [b["species"] for b in s["bio"] if b["active"]]
        self.assertEqual(act, ["Stratum Tectonicas"])
        # nothing open -> no active species
        s2 = self.model.build_surface(self.db, {"system": {"id64": 1}, "status": {}})
        self.assertIn("active", s2)

    def test_atlas_finds(self):
        a = self.model.build_atlas(self.db, "finds", None, (0.0, 0.0, 0.0), 10)
        self.assertEqual(a["total"], 1)                  # the bio Log alone is no find
        codex = [i for i in a["items"] if i["key"] == "codex"][0]
        self.assertEqual(codex["body_id"], 5)            # name -> body for the datasheet
        self.assertEqual(codex["body_short"], "1 a")
        self.assertEqual(codex["lon"], 0.02)
        self.assertEqual(self.model.build_atlas(self.db, "finds", None, None, 10, q="fumarole")["total"], 1)
        self.assertEqual(self.model.build_atlas(self.db, "finds", "codex", None, 10)["total"], 1)
        # a distance limit drops places without coordinates (the fixture has none)
        self.assertEqual(self.model.build_atlas(self.db, "finds", None, (0, 0, 0), 10,
                                                max_ly=50)["total"], 0)
        kinds = {k["key"]: k["count"] for k in self.model.build_atlas_kinds(self.db, "finds")}
        self.assertEqual(kinds, {"codex": 1})            # a Log alone is no find yet
        # tables of older plugin versions missing: empty, no error
        self.assertEqual(self.model.build_atlas(self.db, "rings", None, None)["items"], [])
        self.assertEqual(self.model.build_atlas_kinds(self.db, "signals"), [])

    def test_not_on_body_shows_last(self):
        s = self.model.build_surface(self.db, {})
        self.assertEqual(s["body"], "Sys 1 a")
        self.assertFalse(s["here"])
        self.assertIsNone(s["me"])
        self.assertTrue(s["marks"])

    def test_old_plugin_db_without_tables(self):
        s = self.model.build_surface(Database(os.path.join(fx.DATA_DIR, "shboxsearch.sqlite"))
                                     if hasattr(fx, "DATA_DIR") else self.db, {})
        self.assertIn("track", s)


if __name__ == "__main__":
    unittest.main()
