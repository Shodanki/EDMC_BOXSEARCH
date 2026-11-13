# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
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
        self.assertEqual([leg["body_id"] for leg in route["legs"]], [1])   # DSS+bio open
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
        # I1: never in our database, nobody asked -> "not checked", not "unknown"
        self.assertEqual(br["status"], "unchecked")
        self.assertFalse(br["target"]["in_no_database"])
        self.assertFalse(br["target"]["scoopable"])

    def test_nav_beacon_hint(self):
        import json as _json
        import tempfile as _tf
        from fis import fleet as _fl
        d = _tf.mkdtemp()
        lines = [{"timestamp": "2026-11-11T09:00:00Z", "event": "Commander", "FID": "F1", "Name": "T"},
                 {"timestamp": "2026-11-11T09:30:00Z", "event": "NavBeaconScan",
                  "SystemAddress": fx.SYS_ID, "NumBodies": 4},
                 {"timestamp": "2026-11-11T09:31:00Z", "event": "NavBeaconScan",
                  "SystemAddress": 999, "NumBodies": 30}]
        with open(os.path.join(d, "Journal.2026-11-11T090000.01.log"), "w", encoding="utf-8") as fh:
            fh.write("".join(_json.dumps(x) + chr(10) for x in lines))
        arc = _fl.Archive(d)
        self.assertEqual(self.model.nav_beacon(arc, fx.SYS_ID),
                         {"ts": "2026-11-11T09:30:00Z", "bodies": 4})
        self.assertIsNone(self.model.nav_beacon(arc, 12345))
        sysv = self.model.build_system(self.db, fx.SYS_ID, None, archive=arc)
        self.assertEqual(sysv["nav_beacon"]["bodies"], 4)

    def test_briefing_info_levels(self):
        import sqlite3
        cx = sqlite3.connect(self.db.path)
        rows = [("Inside", 501, 110.0, -20.0, 50.0, 40, "navroute"),
                ("Outside", 502, 900.0, -20.0, 50.0, 40, "navroute"),
                ("Town", 503, 900.0, -20.0, 60.0, 40, "journal,inhabited"),
                ("Guess", 504, 101.0, -20.0, 50.0, 10, "fsdtarget")]
        cx.executemany("INSERT INTO systems (name,id64,x,y,z,quality,sources) VALUES (?,?,?,?,?,?,?)", rows)
        cx.commit()
        cx.close()
        want = {"Inside": "unknown", "Outside": "unchecked", "Town": "inhabited", "Guess": "unchecked"}
        try:
            for name, id64, *_ in rows:
                lt = fed_tracker()
                lt.feed({"timestamp": "2026-11-04T20:12:00Z", "event": "FSDTarget",
                         "Name": name, "SystemAddress": id64, "StarClass": "K"})
                br = self.model.build_briefing(self.db, lt.snapshot())
                self.assertEqual(br["status"], want[name], name)
                self.assertEqual(br["target"]["in_no_database"], name == "Inside", name)
            self.assertEqual(br["target"]["level"], "unchecked")      # estimate only
            sysv = self.model.build_system(self.db, 502, None)
            self.assertEqual(sysv["info_level"], "unchecked")
        finally:
            cx = sqlite3.connect(self.db.path)
            cx.execute("DELETE FROM systems WHERE id64 BETWEEN 501 AND 504")
            cx.commit()
            cx.close()

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

    def test_system_poi(self):
        # M10: stations, carriers (latest first), beacons; USS are left out
        class Ar:
            def refresh(self):
                pass

            def events(self):
                a = fx.SYS_ID
                return [
                    {"event": "FSSSignalDiscovered", "SystemAddress": a, "SignalName": "Old Carrier X1Y-2Z3",
                     "SignalType": "FleetCarrier", "IsStation": True, "timestamp": "2026-11-01T10:00:00Z"},
                    {"event": "FSSSignalDiscovered", "SystemAddress": a, "SignalName": "New Carrier A1B-2C3",
                     "SignalType": "FleetCarrier", "IsStation": True, "timestamp": "2026-11-09T10:00:00Z"},
                    {"event": "FSSSignalDiscovered", "SystemAddress": a, "SignalName": "Test Port",
                     "SignalType": "Outpost", "IsStation": True, "timestamp": "2026-11-02T10:00:00Z"},
                    {"event": "Docked", "SystemAddress": a, "StationName": "Test Port", "StationType": "Outpost",
                     "DistFromStarLS": 512.3, "timestamp": "2026-11-03T10:00:00Z"},
                    {"event": "FSSSignalDiscovered", "SystemAddress": a, "SignalName": "$USS_Type_Salvage;",
                     "SignalType": "USS", "timestamp": "2026-11-03T10:00:00Z"},
                    {"event": "FSSSignalDiscovered", "SystemAddress": a, "SignalName": "Beacon",
                     "SignalType": "NavBeacon", "timestamp": "2026-11-03T10:00:00Z"},
                    {"event": "FSSSignalDiscovered", "SystemAddress": 42, "SignalName": "Elsewhere",
                     "SignalType": "Outpost", "timestamp": "2026-11-03T10:00:00Z"},
                    # 11.11.: docked at the carrier seen in the FSS - one line, name and callsign
                    {"event": "Docked", "SystemAddress": a, "StationName": "X1Y-2Z3",
                     "StationType": "FleetCarrier", "timestamp": "2026-11-02T10:00:00Z"},
                ]
        poi = self.model.system_poi(self.db, fx.SYS_ID, Ar())
        self.assertEqual([(p["kind"], p["name"]) for p in poi],
                         [("station", "Test Port"), ("carrier", "New Carrier A1B-2C3"),
                          ("carrier", "Old Carrier X1Y-2Z3"), ("beacon", "Beacon")])
        self.assertTrue(poi[2]["docked"])
        self.assertEqual(poi[2]["seen"], "2026-11-02T10:00:00Z")
        port = poi[0]
        self.assertTrue(port["docked"])
        self.assertEqual(port["dist_ls"], 512)
        self.assertEqual(self.model.system_poi(self.db, fx.SYS_ID, None), [])

    def test_atlas_systems_and_export(self):
        # M6: the survey sphere's systems by state, M14: the same as a file
        at = self.model.build_atlas(self.db, "systems", None, None, 50)
        states = sorted(it["key"] for it in at["items"])
        self.assertIn("absent", states)
        self.assertEqual(len([s for s in states if s != "absent"]), 2)
        kinds = {k["key"]: k["count"] for k in self.model.build_atlas_kinds(self.db, "systems")}
        self.assertEqual((kinds.get("absent"), kinds.get("only_us")), (1, 1))
        only = self.model.build_atlas(self.db, "systems", "only_us", None, 50)["items"]
        self.assertTrue(only and all(it["only_us"] for it in only))
        csv_text = self.model.survey_export(self.db, "csv")
        lines = csv_text.strip().splitlines()
        self.assertEqual(lines[0].split(",")[:3], ["name", "id64", "x"])
        self.assertEqual(len(lines), 1 + 3)
        js = self.model.survey_export(self.db, "json")
        self.assertEqual(js["survey"]["radius"], 30.0)


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
        self.assertEqual([leg["body_id"] for leg in s["route"]["legs"]],
                         [leg["body_id"] for leg in base["route"]["legs"]])
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
                  "/api/survey", "/api/live", "/api/vehicle"):
            st, js = self.getj(p)
            self.assertEqual(st, 200, p)
            self.assertIsInstance(js, dict, p)
        st, js = self.getj("/api/vehicle")                     # V1c
        self.assertIn("kinds", js["synthesis"])
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

    def test_static_stays_in_the_web_folder(self):
        # S1 (CodeQL path-injection): raw paths, not cleaned up by urllib
        import http.client
        port = self.srv.server_address[1]
        for p in ("/../fis/config.py", "/%2e%2e/fis/config.py", "/js/../../fis/server.py",
                  "/..%5Cfis%5Cconfig.py", "/C:/Windows/win.ini", "//etc/passwd"):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            c.request("GET", p)
            r = c.getresponse()
            r.read()
            self.assertEqual(r.status, 404, p)
            c.close()

    def test_reads_need_a_localhost_host_without_lan(self):
        # 4.10.1: DNS rebinding - another site's page re-points its own name at
        # 127.0.0.1 and reads the API; its Host header gives it away
        import http.client
        port = self.srv.server_address[1]
        for host, want in (("127.0.0.1:%d" % port, 200), ("localhost:%d" % port, 200),
                           ("LOCALHOST:%d" % port, 200), ("[::1]:%d" % port, 200),
                           ("evil.example:%d" % port, 403), ("evil.example", 403),
                           ("127.0.0.1.evil.example:%d" % port, 403)) * 3:
            for path in ("/api/briefing", "/"):
                c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                c.putrequest("GET", path, skip_host=True)
                c.putheader("Host", host)
                c.endheaders()
                r = c.getresponse()
                r.read()
                c.close()
                self.assertEqual(r.status, want, "%s %s" % (host, path))
        # refused hosts do not feed the brake: the own browser still gets in
        st, _js = self.getj("/api/briefing")
        self.assertEqual(st, 200)

    def test_survey_export(self):
        # M14: the survey sphere as a file
        st, h, body = self.get("/api/survey/export?format=csv")
        self.assertEqual(st, 200)
        self.assertIn('attachment; filename="shbox-survey-', h.get("Content-Disposition"))
        self.assertTrue(body.startswith(b"\xef\xbb\xbf"))           # BOM for Excel
        st, h, body = self.get("/api/survey/export?format=json")
        self.assertEqual(json.loads(body)["survey"]["start_system"], fx.SYS)

    def test_static_types(self):
        for p, want in (("/", "text/html; charset=utf-8"), ("/js/i18n.js", "text/javascript; charset=utf-8"),
                        ("/vendor/three/LICENSE", "application/octet-stream")):
            st, h, _b = self.get(p)
            self.assertEqual((st, h.get("Content-Type")), (200, want), p)

    def test_carriers_at_the_jump_target(self):
        # 11.11.: with a jump target the briefing names the carriers THERE
        from fis import carriers
        seen = []
        orig = carriers.carriers_here
        carriers.carriers_here = lambda id64, name, own, favs, now=None: seen.append((id64, name)) or []
        try:
            live = {"system": {"id64": 1, "name": "Here"}}
            self.app._cache.clear()
            self.app.carriers_here(dict(live, target={"name": "There", "id64": 2}))
            self.app._cache.clear()
            self.app.carriers_here(live)
        finally:
            carriers.carriers_here = orig
        self.assertEqual(seen, [(2, "There"), (1, "Here")])
        st, js = self.getj("/api/briefing")
        self.assertIn(js["carriers_where"], ("target", "here"))

    def test_static_revalidated_not_refetched(self):
        # 11.11.: a tablet fetched Three.js (1.3 MB) on every load - now 304
        import http.client
        port = self.srv.server_address[1]
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("GET", "/vendor/three/three.module.js")
        r = c.getresponse()
        r.read()
        etag = r.getheader("ETag")
        self.assertEqual((r.status, r.getheader("Cache-Control")), (200, "no-cache"))
        self.assertTrue(etag)
        c.request("GET", "/vendor/three/three.module.js", headers={"If-None-Match": etag})
        r = c.getresponse()
        self.assertEqual((r.status, r.read()), (304, b""))
        c.close()
        st, h, _b = self.get("/api/health")
        self.assertEqual(h.get("Cache-Control"), "no-store")            # data never cached

    def test_sse(self):
        req = urllib.request.Request(self.base + "/api/events")
        r = urllib.request.urlopen(req, timeout=5)
        try:
            self.assertEqual(r.headers.get_content_type(), "text/event-stream")
            first = r.readline().decode()
            self.assertEqual(first.strip(), "event: snapshot")
            r.readline()
            r.readline()
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


class TestPing(_Base):
    """A quiet game: the event stream still sends a named ping with the
    watchdog state - the page's watchdog can see it (SSE comments it cannot)."""
    def test_ping_when_quiet(self):
        from fis.server import Handler
        app = App(self.cfg, live=fed_tracker(self.tmp), db=self.db)
        old = Handler.PING_S
        Handler.PING_S = 0.3
        srv = make_server(app, host="127.0.0.1", port=0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            r = urllib.request.urlopen("http://127.0.0.1:%d/api/events" % srv.server_address[1], timeout=5)
            seen = []
            for _ in range(40):
                ln = r.readline().decode("utf-8").strip()
                seen.append(ln)
                if ln == "event: ping":
                    data = json.loads(r.readline().decode("utf-8")[len("data: "):])
                    self.assertIn("journal_rewrites", data)
                    self.assertIn("poll_age_s", data)
                    break
            else:
                self.fail("no ping: %r" % seen[-5:])
            r.close()
        finally:
            Handler.PING_S = old
            srv.shutdown()
            srv.server_close()


class TestSettings(_Base):
    """The settings page: game PC only, FIS page only (custom header, origin)."""
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cfg.ini_path = os.path.join(cls.tmp, "fis.ini")
        cls.app = App(cls.cfg, live=fed_tracker(cls.tmp), db=cls.db)
        cls.srv = make_server(cls.app, host="127.0.0.1", port=0)
        cls.cfg.port = cls.srv.server_address[1]
        cls.base = "http://127.0.0.1:%d" % cls.cfg.port
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def _post(self, body, headers):
        req = urllib.request.Request(self.base + "/api/settings", data=json.dumps(body).encode(),
                                     headers=dict({"Content-Type": "application/json"}, **headers), method="POST")
        return urllib.request.urlopen(req, timeout=5)

    def test_read(self):
        with urllib.request.urlopen(self.base + "/api/settings", timeout=5) as r:
            d = json.loads(r.read())
        self.assertIn(d["language"], ("en", "de"))
        self.assertFalse(d["lan"])

    def test_post_needs_header_and_own_origin(self):
        for headers in ({}, {"X-FIS-Settings": "1", "Origin": "http://evil.example"}):
            with self.assertRaises(urllib.error.HTTPError) as e:
                self._post({"language": "de"}, headers)
            self.assertEqual(e.exception.code, 403)
            e.exception.close()

    def test_post_saves(self):
        with self._post({"language": "de", "open_browser": False, "lan": False},
                        {"X-FIS-Settings": "1", "Origin": self.base}) as r:
            d = json.loads(r.read())
        self.assertTrue(d["saved"])
        self.assertEqual(d["language"], "de")
        with open(self.cfg.ini_path, encoding="utf-8") as fh:
            ini = fh.read()
        self.assertIn("language = de", ini)
        self.assertIn("open_browser = false", ini)

    def test_internal_error_tells_no_details(self):
        """N10: a failure answers 500 without the exception's text (paths,
        names) - that stays in the FIS console."""
        from unittest import mock
        from fis import server
        boom = RuntimeError(r"C:\Users\Someone\secret.sqlite is locked")
        with mock.patch.object(server.Handler, "_api", side_effect=boom), \
                mock.patch("traceback.print_exc"):
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(self.base + "/api/health", timeout=5)
        body = e.exception.read().decode("utf-8", "replace")
        e.exception.close()
        self.assertEqual(e.exception.code, 500)
        self.assertIn("internal error", body)
        self.assertNotIn("secret", body)
        self.assertNotIn("RuntimeError", body)

    def test_unsold_limits(self):
        """4.11: the UNSOLD DATA limits are read, saved, clamped; a bad value
        changes nothing at all, not even the other fields of the request."""
        hdr = {"X-FIS-Settings": "1", "Origin": self.base}
        with urllib.request.urlopen(self.base + "/api/settings", timeout=5) as r:
            d = json.loads(r.read())
        self.assertEqual(d["unsold_defaults"], {"sell_mcr": 50, "sell_systems": 100,
                                                "moderate_mcr": 50, "high_mcr": 100})
        with self._post({"unsold": {"moderate_mcr": "200", "high_mcr": 150, "sell_mcr": 300,
                                    "sell_systems": 0}}, hdr) as r:
            d = json.loads(r.read())
        # high never below moderate, at least 1 system
        self.assertEqual(d["unsold"], {"sell_mcr": 300, "sell_systems": 1, "moderate_mcr": 200, "high_mcr": 200})
        with open(self.cfg.ini_path, encoding="utf-8") as fh:
            ini = fh.read()
        self.assertIn("unsold_moderate_mcr = 200", ini)
        lang = self.cfg.language
        with self.assertRaises(urllib.error.HTTPError) as e:
            self._post({"language": "en" if lang == "de" else "de", "unsold": {"high_mcr": "lots"}}, hdr)
        self.assertEqual(e.exception.code, 400)
        e.exception.close()
        self.assertEqual((self.cfg.unsold["high_mcr"], self.cfg.language), (200, lang))


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

    def test_page_cookie_is_the_stored_token(self):
        # the cookie carries the stored token - nothing a request sends ends
        # up in a header (S1: CodeQL http-response-splitting)
        with urllib.request.urlopen(self.base + "/?token=secret-token", timeout=5) as r:
            self.assertIn("fis_token=secret-token;", r.headers.get("Set-Cookie", ""))
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.srv.server_address[1], timeout=5)
        c.request("GET", "/?token=secret-token%0d%0aX-Evil:%201")
        r = c.getresponse()
        r.read()
        self.assertEqual(r.status, 401)               # not the stored token
        self.assertIsNone(r.getheader("X-Evil"))
        c.close()


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
