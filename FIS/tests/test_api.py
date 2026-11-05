"""Data layer, model and HTTP API (MVP item 1)."""

import json
import os
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from fis.config import Config
from fis.data import Database
from fis.live import LiveTracker
from fis.server import App, make_server

from tests import fixtures as fx


def make_cfg(db_path, journal_dir):
    cfg = Config()
    cfg.ini_path = os.path.join(tempfile.gettempdir(), "fis-test-none.ini")
    cfg.db_path = db_path
    cfg.journal_dir = journal_dir
    cfg.plugin_dir = fx.PLUGIN_DIR
    cfg.use_plugin_path()
    return cfg


def fed_tracker(journal_dir="."):
    lt = LiveTracker(journal_dir)
    lt._replaying = True
    for e in fx.journal_lines():
        lt.feed(e)
    lt._replaying = False
    return lt


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="fis-test-")
        cls.db_path = fx.make_db(os.path.join(cls.tmp, "db.sqlite"))
        cls.cfg = make_cfg(cls.db_path, cls.tmp)
        cls.db = Database(cls.db_path)
        from fis import model
        cls.model = model


class TestData(_Base):
    def test_read_only(self):
        cx = self.db.connect()
        try:
            with self.assertRaises(sqlite3.OperationalError):
                cx.execute("INSERT INTO meta VALUES ('x','y')")
        finally:
            cx.close()

    def test_missing_db_is_empty(self):
        d = Database(os.path.join(self.tmp, "nope.sqlite"))
        self.assertFalse(d.exists)
        self.assertIsNone(d.system_by_id64(1))
        self.assertEqual(d.health()["exists"], False)

    def test_lookup(self):
        self.assertEqual(self.db.system_by_name(fx.SYS.lower())["id64"], fx.SYS_ID)
        self.assertEqual(len(self.db.bodies_of(fx.SYS_ID)), 4)
        self.assertEqual(Database.known_sources(self.db.system_by_id64(fx.NEXT_ID)), ["EDSM"])

    def test_health(self):
        h = self.db.health()
        self.assertTrue(h["ok"])
        self.assertEqual(h["systems"], 2)


class TestModel(_Base):
    def test_system_positions_and_route(self):
        live = fed_tracker().snapshot()
        s = self.model.build_system(self.db, fx.SYS_ID, live, ["todo"])
        self.assertEqual(s["name"], fx.SYS)
        by = {b["body_id"]: b for b in s["bodies"]}
        self.assertEqual(by[0]["pos"], [0.0, 0.0, 0.0])
        r1 = sum(v * v for v in by[1]["pos"]) ** 0.5
        self.assertAlmostEqual(r1, 500.0, delta=10.0)       # Kepler, ~a(1-e cos E)
        moon = by[2]
        dm = sum((moon["pos"][i] - by[1]["pos"][i]) ** 2 for i in range(3)) ** 0.5
        self.assertAlmostEqual(dm, 1.0, delta=0.05)
        self.assertTrue(moon["moon"])
        self.assertEqual(len(by[1]["orbit"]), 73)
        self.assertTrue(by[1]["flags"]["first"])
        self.assertEqual(by[1]["flags"]["bio"], 2)
        self.assertEqual(by[3]["rings"][0]["cls"], "Icy")
        route = s["route"]
        self.assertEqual([l["body_id"] for l in route["legs"]], [1])   # DSS+bio open
        self.assertRegex(route["legs"][0]["label"], r"^LEG 1 · 49\d LS · ~\d+ min$")
        self.assertEqual(route["next"], 1)

    def test_fix_after_jump_is_arrival_star(self):
        live = fed_tracker().snapshot()
        s = self.model.build_system(self.db, fx.SYS_ID, live, ["todo"])
        self.assertEqual(s["fix"]["body_id"], 0)
        self.assertFalse(s["fix"]["exact"])
        self.assertIn("LAST FIX", s["fix"]["label"])

    def test_fix_from_approach(self):
        lt = fed_tracker()
        lt.feed({"timestamp": "2026-11-04T20:20:00Z", "event": "ApproachBody",
                 "StarSystem": fx.SYS, "SystemAddress": fx.SYS_ID,
                 "Body": fx.SYS + " 1", "BodyID": 1})
        s = self.model.build_system(self.db, fx.SYS_ID, lt.snapshot(), ["todo"])
        self.assertEqual(s["fix"]["short"], "1")
        self.assertEqual(s["fix"]["event"], "ApproachBody")

    def test_fix_from_status_by_name(self):
        lt = fed_tracker()
        lt.feed_status({"timestamp": "2026-11-04T20:30:00Z", "event": "Status", "Flags": 1 << 21,
                        "Latitude": 3.0, "Longitude": 4.0, "Altitude": 1000.0,
                        "BodyName": fx.SYS + " 1 a"})
        s = self.model.build_system(self.db, fx.SYS_ID, lt.snapshot(), ["todo"])
        self.assertEqual((s["fix"]["body_id"], s["fix"]["event"]), (2, "Status"))
        self.assertEqual(s["fix"]["lat"], 3.0)

    def test_unknown_system(self):
        s = self.model.build_system(self.db, 42, None)
        self.assertEqual(s["bodies"], [])
        self.assertFalse(s["known"])

    def test_body_sheet(self):
        b = self.model.build_body(self.db, fx.SYS_ID, 1)
        self.assertAlmostEqual(b["gravity_g"], 2.5 / 9.80665, places=3)
        self.assertAlmostEqual(b["pressure_atm"], 1500.0 / 101325.0, places=4)
        self.assertEqual(b["atmo_comp"][0][0], "CarbonDioxide")
        self.assertEqual(b["composition"][0], ["Rock", 90.0])
        self.assertEqual(b["rotation_d"], 3.0)
        self.assertTrue(b["tidal_lock"])
        self.assertEqual(b["short"], "1")
        self.assertEqual(b["bio"]["signals"], 2)
        self.assertEqual([p["genus"] for p in b["bio"]["prediction"]], ["Bacterium"])
        self.assertIsNone(self.model.build_body(self.db, fx.SYS_ID, 77))
        star = self.model.build_body(self.db, fx.SYS_ID, 0)
        self.assertTrue(star["star"]["scoopable"])

    def test_briefing(self):
        live = fed_tracker().snapshot()
        br = self.model.build_briefing(self.db, live)
        t = br["target"]
        self.assertEqual(t["name"], fx.NEXT)
        self.assertEqual(t["star_class"], "M")
        self.assertTrue(t["scoopable"])
        self.assertAlmostEqual(t["distance_ly"], 5.0, places=2)
        self.assertEqual(br["status"], "known")
        self.assertEqual(br["boxel"]["key"], "Testia AB-C d1")
        self.assertEqual(br["boxel"]["candidates_open"], 7)   # 0..9 minus 5, 6, 7
        self.assertIn("after_t", br["fuel"])
        self.assertLess(br["fuel"]["after_t"], 140.0)
        sp = br["sphere"]
        self.assertIsNotNone(sp)
        self.assertTrue(sp["inside"])
        self.assertLessEqual(sp["from_centre_ly"], 30.0)

    def test_briefing_unknown_target(self):
        lt = fed_tracker()
        lt.feed({"timestamp": "2026-11-04T20:12:00Z", "event": "FSDTarget",
                 "Name": "Testia AB-C d1-8", "SystemAddress": 77,
                 "StarClass": "Y", "RemainingJumpsInRoute": 1})
        br = self.model.build_briefing(self.db, lt.snapshot())
        self.assertEqual(br["status"], "unknown")
        self.assertFalse(br["target"]["scoopable"])

    def test_briefing_only_us_and_range(self):
        lt = fed_tracker()
        # the visited system itself, which no public database knows, far away
        lt.feed({"timestamp": "2026-11-04T20:12:00Z", "event": "Location",
                 "StarSystem": "Far", "SystemAddress": 3, "StarPos": [500.0, -20.0, 50.0]})
        lt.feed({"timestamp": "2026-11-04T20:13:00Z", "event": "FSDTarget",
                 "Name": fx.SYS, "SystemAddress": fx.SYS_ID, "StarClass": "K"})
        br = self.model.build_briefing(self.db, lt.snapshot())
        self.assertEqual(br["status"], "only_us")
        self.assertTrue(br["fuel"]["beyond_range"])        # 400 ly > 68.3 ly
        self.assertNotIn("after_t", br["fuel"])

    def test_navroute_target_fallback(self):
        live = fed_tracker().snapshot()
        live["target"] = None
        hops = [{"name": "Start", "id64": 1}, {"name": fx.SYS, "id64": fx.SYS_ID},
                {"name": fx.NEXT, "id64": fx.NEXT_ID}]
        live["navroute"] = hops
        self.assertEqual(self.model.current_target(live)["name"], fx.NEXT)
        live["navroute"] = hops[:2]                       # we are at the end
        self.assertIsNone(self.model.current_target(live))
        live["navroute"] = [{"name": "Elsewhere", "id64": 9}, {"name": "Far", "id64": 8}]
        self.assertIsNone(self.model.current_target(live))  # not on this route

    def test_ship(self):
        sh = self.model.build_ship(fed_tracker().snapshot())
        self.assertEqual(sh["ship"]["name"], "TESTHAWK")
        self.assertEqual(sh["fuel"]["main"], 140.0)
        self.assertIsNotNone(sh["fuel"]["jumps_left"])

    def test_survey(self):
        sv = self.model.build_survey(self.db)
        self.assertTrue(sv["active"])
        self.assertEqual(sv["systems"]["known"], 2)
        self.assertEqual(sv["systems"]["visited"], 1)
        self.assertEqual(sv["systems"]["only_us"], 1)


@unittest.skipUnless(os.path.exists(fx.REAL_DB), "no copy of a real database in tests/data")
class TestRealData(unittest.TestCase):
    """Smoke tests against the copy of the commander's database."""

    @classmethod
    def setUpClass(cls):
        make_cfg(fx.REAL_DB, ".")
        from fis import model
        cls.model = model
        cls.db = Database(fx.REAL_DB)

    def test_hip_31189(self):
        row = self.db.system_by_name("HIP 31189")
        s = self.model.build_system(self.db, row["id64"], None)
        self.assertGreater(len(s["bodies"]), 10)
        self.assertTrue(s["route"]["legs"])
        for b in s["bodies"]:
            self.assertEqual(len(b["pos"]), 3)

    def test_order_model_keeps_order_times_use_measured(self):
        """Order planned with the plugin's model, times with the measured one."""
        sr = self.model.plugin().sysroute
        row = self.db.system_by_name("HIP 31189")
        now = 1.8e9
        base = self.model.build_system(self.db, row["id64"], None, ["all"], now=now)
        fast = sr.CostModel(entry=80.0, k=4.0)
        s = self.model.build_system(self.db, row["id64"], None, ["all"], now=now,
                                    cost_model=fast, order_model=sr.DEFAULT_MODEL)
        self.assertEqual([l["body_id"] for l in s["route"]["legs"]],
                         [l["body_id"] for l in base["route"]["legs"]])
        self.assertLess(s["route"]["total_min"], base["route"]["total_min"])
        self.assertTrue(s["route"]["calibrated"])
        self.assertFalse(base["route"]["calibrated"])

    def test_synuefe_body_sheets(self):
        row = self.db.system_by_name("Synuefe MQ-M b40-0")
        s = self.model.build_system(self.db, row["id64"], None)
        for b in s["bodies"]:
            sheet = self.model.build_body(self.db, row["id64"], b["body_id"])
            self.assertIsNotNone(sheet)
            json.dumps(sheet)


class TestServer(_Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.lt = fed_tracker(cls.tmp)
        cls.app = App(cls.cfg, live=cls.lt, db=cls.db)
        cls.srv = make_server(cls.app, host="127.0.0.1", port=0)
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        cls.th = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.th.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def get(self, path, headers=None):
        req = urllib.request.Request(self.base + path, headers=headers or {})
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.headers, r.read()

    def getj(self, path):
        st, _h, body = self.get(path)
        return st, json.loads(body)

    def test_endpoints(self):
        for p in ("/api/health", "/api/system/current", "/api/system/%d" % fx.SYS_ID,
                  "/api/body/%d/1" % fx.SYS_ID, "/api/briefing", "/api/ship",
                  "/api/survey", "/api/live"):
            st, js = self.getj(p)
            self.assertEqual(st, 200, p)
            self.assertIsInstance(js, dict, p)
        st, js = self.getj("/api/system/current")
        self.assertEqual(js["id64"], fx.SYS_ID)
        st, js = self.getj("/api/health")
        self.assertFalse(js["ai_at_runtime"])

    def test_config_language(self):
        st, js = self.getj("/api/config")
        self.assertEqual(st, 200)
        self.assertIn(js["language"], ("en", "de"))
        self.assertNotIn("token", js)

    def test_404(self):
        for p in ("/api/body/%d/99" % fx.SYS_ID, "/api/nope", "/../fis/config.py"):
            with self.assertRaises(urllib.error.HTTPError) as cm:
                self.get(p)
            self.assertEqual(cm.exception.code, 404, p)
            cm.exception.close()

    def test_sse(self):
        req = urllib.request.Request(self.base + "/api/events")
        r = urllib.request.urlopen(req, timeout=5)
        try:
            self.assertEqual(r.headers.get_content_type(), "text/event-stream")
            first = r.readline().decode()
            self.assertEqual(first.strip(), "event: snapshot")
            r.readline(); r.readline()
            self.app.hub.publish("jump", {"x": 1})
            ev = r.readline().decode().strip()
            data = r.readline().decode().strip()
            self.assertEqual(ev, "event: jump")
            self.assertEqual(json.loads(data[len("data: "):]), {"x": 1})
        finally:
            r.close()


class TestDbWatch(_Base):
    def test_db_change_publishes_scan(self):
        import time
        app = App(self.cfg, live=fed_tracker(self.tmp), db=self.db)
        q = app.hub.subscribe()
        app.watch_db(interval=0.05)
        try:
            time.sleep(0.15)
            future = time.time() + 10
            os.utime(self.db_path, (future, future))
            ev = q.get(timeout=2)
            self.assertEqual(ev[0], "scan")
            self.assertEqual(ev[1]["source"], "db")
        finally:
            app.stop()


class TestLanToken(_Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cfg.lan = True
        cls.cfg.token = "secret-token"
        cls.app = App(cls.cfg, live=fed_tracker(cls.tmp), db=cls.db)
        cls.srv = make_server(cls.app, host="127.0.0.1", port=0)
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.cfg.lan = False

    def test_token(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(self.base + "/api/health", timeout=5)
        self.assertEqual(cm.exception.code, 401)
        cm.exception.close()
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(self.base + "/api/health?token=wrong", timeout=5)
        cm.exception.close()
        with urllib.request.urlopen(self.base + "/api/health?token=secret-token", timeout=5) as r:
            self.assertEqual(r.status, 200)
        req = urllib.request.Request(self.base + "/api/ship",
                                     headers={"X-FIS-Token": "secret-token"})
        with urllib.request.urlopen(req, timeout=5) as r:
            self.assertEqual(r.status, 200)


if __name__ == "__main__":
    unittest.main()


class TestPortBusy(unittest.TestCase):
    """Second double-click: port taken -> clear message, exit code 2, no traceback."""

    def test_port_busy(self):
        import contextlib
        import io
        import socket
        from fis import server as srv_mod
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        ini = os.path.join(tempfile.gettempdir(), "fis-test-none.ini")
        out = io.StringIO()
        try:
            with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(out):
                rc = srv_mod.main(["--ini", ini, "--no-setup", "--port", str(port),
                                   "--db", os.path.join(tmp, "none.sqlite"), "--journal", tmp])
        finally:
            sock.close()
        self.assertEqual(rc, 2)
        self.assertIn("in use", out.getvalue())
