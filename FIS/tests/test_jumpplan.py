# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""5.0 CARRIER > JUMP PLAN: jump times learnt from your own jumps, the
route over your own systems and EDDiscovery's, tritium per jump, the plan
file and ticking off by the carrier's position."""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from fis import jumpplan
from fis.server import App, make_server
from tests.test_api import _Base, fed_tracker


def _req(ts, dep, to):
    return {"event": "CarrierJumpRequest", "timestamp": ts, "DepartureTime": dep, "SystemName": to}


def _loc(ts, name):
    return {"event": "CarrierLocation", "timestamp": ts, "StarSystem": name}


JUMPS = [
    _req("2026-05-01T10:00:00Z", "2026-05-01T10:15:00Z", "Demo A"), _loc("2026-05-01T10:15:00Z", "Demo A"),
    _req("2026-05-01T10:21:00Z", "2026-05-01T10:37:00Z", "Demo B"), _loc("2026-05-01T10:37:00Z", "Demo B"),
    _req("2026-05-01T11:00:00Z", "2026-05-01T11:25:00Z", "Demo C"), _loc("2026-05-01T11:25:00Z", "Demo C"),
]


class TimingTest(unittest.TestCase):
    def test_learnt_from_own_jumps(self):
        tm = jumpplan.timing(JUMPS)
        c = tm["countdown"]
        self.assertTrue(c["learnt"])
        self.assertEqual(c["n"], 3)
        self.assertEqual(c["mid"], 16.0)            # 15, 16, 25 minutes
        self.assertEqual((c["lo"], c["hi"]), (15.2, 23.2))
        self.assertEqual(tm["cooldown"], 5.0)
        self.assertEqual(tm["fastest_next"], 6.0)   # arrived 10:15, next order 10:21
        self.assertEqual(tm["per_jump"], 21.0)

    def test_prior_without_jumps(self):
        tm = jumpplan.timing([])
        self.assertFalse(tm["countdown"]["learnt"])
        self.assertEqual(tm["countdown"]["mid"], 15.0)
        self.assertIsNone(tm["fastest_next"])

    def test_broken_times_are_skipped(self):
        evs = [_req("2026-05-01T10:00:00Z", None, "X"), _req("2026-05-01T10:00:00Z", "2026-05-01T09:00:00Z", "X")]
        self.assertEqual(jumpplan.timing(evs)["countdown"]["n"], 0)

    def test_trip_time_no_cooldown_after_the_last(self):
        tm = jumpplan.timing(JUMPS)
        tt = jumpplan.trip_time(3, tm)
        self.assertEqual(tt["mid"], 3 * 16 + 2 * 5)
        self.assertEqual(tt["lo"], round(3 * 15.2 + 10))
        self.assertEqual(tt["hi"], round(3 * 23.2 + 10))
        self.assertEqual(tt["n"], 3)
        self.assertIsNone(jumpplan.trip_time(0, tm))


def _line(n, step, prefix="Own"):
    """n systems along the x axis, `step` ly apart (all invented)."""
    return [{"name": "%s %d" % (prefix, i), "id64": 1000 + i, "pos": (i * step, 0.0, 0.0)} for i in range(1, n + 1)]


START = {"name": "Start", "pos": (0.0, 0.0, 0.0)}
TARGET = {"name": "Target", "id64": 9, "pos": (1400.0, 0.0, 0.0)}


class FakeEdd:
    """Stands in for EDDiscovery's star database: a dense row of stars."""
    src = "edd"

    def __init__(self, stars):
        self.stars = jumpplan.OwnStars(stars)
        for s in self.stars.by_name.values():
            s["src"] = "edd"

    def near(self, center, radius):
        return self.stars.near(center, radius)


class RouteTest(unittest.TestCase):
    def test_own_systems_fewest_jumps(self):
        own = jumpplan.OwnStars(_line(14, 100.0))        # 100 ly apart up to 1400
        hops = jumpplan.route_own(START, TARGET, own)
        self.assertEqual(len(hops), 3)                   # 500, 1000, target
        self.assertEqual(hops[-1]["name"], "Target")
        legs = jumpplan._legs(START["pos"], hops)
        self.assertTrue(all(lg <= 500.0 for lg in legs))

    def test_gap_in_own_data_needs_edd(self):
        own = jumpplan.OwnStars(_line(3, 100.0))         # nothing beyond 300 ly
        r = jumpplan.plan_route(START, TARGET, own)
        self.assertIsNone(r["hops"])
        self.assertIsNone(r["source"])
        edd = FakeEdd(_line(30, 50.0, "Edd"))
        r = jumpplan.plan_route(START, TARGET, own, edd)
        self.assertEqual(r["source"], "own+edd")
        self.assertTrue(r["checked_edd"])
        self.assertEqual(len(r["hops"]), 3)
        self.assertEqual(r["ideal"], 3)

    def test_edd_only_checks_when_own_is_as_good(self):
        own = jumpplan.OwnStars(_line(14, 100.0))
        edd = FakeEdd(_line(30, 50.0, "Edd"))
        r = jumpplan.plan_route(START, TARGET, own, edd)
        self.assertEqual(r["source"], "own")             # same jumps: your own data wins
        self.assertTrue(r["checked_edd"])

    def test_target_from_edd_names_the_source(self):
        own = jumpplan.OwnStars(_line(14, 100.0))
        target = dict(TARGET, src="edd")
        plan = jumpplan.make_plan(START, target, own, None, 0.0)
        self.assertEqual(plan["source"], "own+edd")

    def test_target_within_one_jump(self):
        near = {"name": "Near", "pos": (300.0, 0.0, 0.0)}
        self.assertEqual(jumpplan.route_own(START, near, jumpplan.OwnStars([])), [near])

    def test_resolve_by_name_and_id64(self):
        own = jumpplan.OwnStars(_line(3, 100.0))
        self.assertEqual(jumpplan.resolve(own, None, name="own 2")["id64"], 1002)
        self.assertEqual(jumpplan.resolve(own, None, id64=1003)["name"], "Own 3")
        self.assertIsNone(jumpplan.resolve(own, None, name="Nowhere"))

    def test_edd_name_keys_invert_the_plugins_decoding(self):
        import sources      # the plugin's reader (tests put the plugin folder on sys.path)
        dec = sources.EDDiscoverySource.decode_nameid
        for sector, rest in (("Col 285 Sector", "XY-Z c6-5"), ("Prua Phoe", "AB-C d1-23"), ("Eol Prou", "QR-S b4-10")):
            self.assertEqual(dec(jumpplan._std_nameid(rest), sector), sector + " " + rest)
        for sector, rest in (("HIP", "31330"), ("EXO", "1846-031")):
            self.assertEqual(dec(jumpplan._num_nameid(rest), sector), sector + " " + rest)
        self.assertIsNone(jumpplan._std_nameid("Colonia"))
        self.assertIsNone(jumpplan._num_nameid("12-34-5"))


class FuelTest(unittest.TestCase):
    def test_refuel_from_the_hold_before_the_jump_that_needs_it(self):
        rows = jumpplan.fuel_rows([500.0] * 3, load=8000.0, tank=150, hold=600)
        self.assertEqual(rows[0]["need"], 104)           # 5 + 500 * (8000 + 150 + 26500) / 175000
        self.assertNotIn("refuel", rows[0])
        self.assertIn("refuel", rows[1])                 # 46 t left, 104 needed
        self.assertEqual(rows[1]["refuel"]["min"], rows[1]["need"] - 46)
        self.assertEqual(rows[1]["refuel"]["fill"], 600)   # all of the hold fits the tank
        self.assertFalse(any(r["short"] for r in rows))

    def test_short_without_tritium(self):
        rows = jumpplan.fuel_rows([500.0, 500.0], load=8000.0, tank=120, hold=0)
        self.assertFalse(rows[0]["short"])
        self.assertTrue(rows[1]["short"])
        self.assertEqual(rows[1]["refuel"]["short"], rows[1]["need"] - rows[0]["tank_after"])


class StoreAndTickTest(unittest.TestCase):
    def test_plan_file_per_commander_and_broken_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "jump_plan.json")
            st = jumpplan.PlanStore(path)
            self.assertIsNone(st.get("F1")["plan"])
            st.set_plan("F1", {"hops": [1]})
            st.report_full("F1", {"system": "Target", "ts": 1.0})
            self.assertEqual(jumpplan.PlanStore(path).get("F1")["plan"], {"hops": [1]})
            self.assertEqual(len(st.get("F1")["full"]), 1)
            self.assertIsNone(st.get("F2")["plan"])
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{broken")
            self.assertIsNone(st.get("F1")["plan"])
            self.assertTrue(os.path.exists(path + ".bad"))
            st.set_plan("F1", None)
            with open(path, encoding="utf-8") as fh:
                self.assertIn("cmdrs", json.load(fh))

    def test_tick_off_in_order_after_the_plan(self):
        hops = [{"name": "A"}, {"name": "B"}, {"name": "C"}]
        created = jumpplan.parse_ts("2026-05-01T10:00:00Z")
        evs = [_loc("2026-05-01T09:00:00Z", "B"),        # before the plan: not counted
               _loc("2026-05-01T10:20:00Z", "A"),
               _loc("2026-05-01T11:00:00Z", "A"),        # a login again
               _loc("2026-05-01T12:00:00Z", "C")]        # B skipped: C still counts
        self.assertEqual(jumpplan.progress(hops, evs, created),
                         {0: "2026-05-01T10:20:00Z", 2: "2026-05-01T12:00:00Z"})

    def test_build_rows(self):
        plan = jumpplan.make_plan(START, TARGET, jumpplan.OwnStars(_line(14, 100.0)), None,
                                  jumpplan.parse_ts("2026-05-01T09:00:00Z"))
        evs = JUMPS + [_loc("2026-05-01T12:00:00Z", plan["hops"][0]["name"])]
        out = jumpplan.build(plan, {"fuel": 1000, "load": 8000}, evs, 0, 0.0)
        rows = out["rows"]
        self.assertEqual(len(rows), 3)
        self.assertTrue(rows[0]["done"])
        self.assertTrue(rows[1]["next"])
        self.assertEqual(out["left"], 2)
        self.assertEqual(rows[1]["minutes"], 21.0)       # countdown 16 + cooldown 5
        self.assertEqual(rows[2]["minutes"], 16.0)       # the last: no cooldown
        self.assertEqual(rows[2]["at"], 37)
        self.assertEqual(out["total"]["mid"], 37)
        self.assertFalse(out["arrived"])


# Spansh's fleet carrier export, its layout with invented systems and values
SPANSH_JSON = {"created_at": "2026-11-19T08:00:00", "job": "DEMO-JOB", "parameters": {"capacity_used": 14000},
               "result": {"jumps": [
                   {"name": "Demo Home", "id64": "11", "x": 0, "y": 0, "z": 0, "distance": 0, "fuel_used": 0,
                    "must_restock": 1, "has_icy_ring": False, "is_system_pristine": False},
                   {"name": "Demo 5", "id64": "15", "x": 500, "y": 0, "z": 0, "distance": 500.0, "fuel_used": 113,
                    "must_restock": 0, "has_icy_ring": True, "is_system_pristine": True},
                   {"name": "Demo 9", "id64": "19", "x": 900, "y": 0, "z": 0, "distance": 400.0, "fuel_used": 90,
                    "must_restock": 0, "has_icy_ring": False, "is_system_pristine": False}]}}
SPANSH_CSV = ('"System Name","Distance","Distance Remaining","Tritium in tank","Tritium in market","Fuel Used",'
              '"Icy Ring","Pristine","Restock Tritium"\n'
              '"Demo Home","0","900","","0","0","No","No","Yes"\n'
              '"Demo 5","500","400","","0","113","Yes","Yes","No"\n'
              '"Demo 9","400","0","","0","90","No","No","No"\n')


class SpanshTest(unittest.TestCase):
    def test_json_and_csv(self):
        j = jumpplan.parse_spansh(json.dumps(SPANSH_JSON))
        c = jumpplan.parse_spansh("\ufeff" + SPANSH_CSV)
        self.assertEqual([x["name"] for x in j], ["Demo Home", "Demo 5", "Demo 9"])
        self.assertEqual([x["name"] for x in c], [x["name"] for x in j])
        self.assertEqual((j[1]["pos"], j[1]["id64"], j[1]["spansh_fuel"], j[1]["icy_ring"]), ([500, 0, 0], 15, 113, True))
        self.assertEqual((c[1]["pos"], c[1]["spansh_fuel"], c[1]["icy_ring"], c[0]["restock"]), (None, 113, True, True))
        for bad in ("", "{}", "{broken", "a,b\n1,2", json.dumps({"result": {"jumps": [{"x": 1}]}})):
            self.assertIsNone(jumpplan.parse_spansh(bad), bad)

    def test_plan_from_csv_takes_positions_from_your_data(self):
        own = jumpplan.OwnStars([{"name": "Demo 5", "id64": 15, "pos": (500.0, 0, 0)}])
        p = jumpplan.spansh_plan(jumpplan.parse_spansh(SPANSH_CSV), own, None, 0.0)
        self.assertEqual(p["source"], "spansh")
        self.assertEqual(p["start"]["name"], "Demo Home")
        self.assertEqual([h["name"] for h in p["hops"]], ["Demo 5", "Demo 9"])
        self.assertEqual(p["hops"][0]["pos"], [500.0, 0, 0])
        self.assertIsNone(p["hops"][1]["pos"])          # unknown here: its distance from Spansh is used
        self.assertEqual(p["spansh_need"], 203)
        self.assertEqual(jumpplan._legs(None, p["hops"]), [500.0, 400.0])   # Spansh's distances
        self.assertIsNone(jumpplan.spansh_plan(jumpplan.parse_spansh(SPANSH_CSV)[:1], own, None, 0.0))

    def test_help_fields(self):
        h = jumpplan.spansh_help({"system": "Demo Home", "used": 14000, "fuel": 900},
                                 {"target": {"name": "Demo 9"}}, 250)
        self.assertEqual((h["source"], h["destination"], h["used"], h["tank"], h["hold"]),
                         ("Demo Home", "Demo 9", 14000, 900, 250))
        self.assertTrue(h["url"].startswith("https://spansh.co.uk/"))


def _fsd(ts, name, pos):
    return {"timestamp": ts, "event": "FSDJump", "StarSystem": name, "StarPos": list(pos)}


class ApiTest(_Base):
    """GET /api/jumpplan and POST plan/clear against a scripted journal."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.jd = tempfile.mkdtemp()
        lines = [{"timestamp": "2026-11-01T09:00:00Z", "event": "Commander", "FID": "F7", "Name": "Tester"}]
        lines += [_fsd("2026-11-01T09:%02d:00Z" % i, "Demo %d" % i, (i * 100.0, 0, 0)) for i in range(1, 15)]
        lines += [_fsd("2026-11-01T09:30:00Z", "Demo Home", (0, 0, 0)),
                  {"timestamp": "2026-11-01T09:31:00Z", "event": "CarrierStats", "CarrierID": 77, "Callsign": "Q2W-3ER",
                   "FuelLevel": 900, "SpaceUsage": {"TotalCapacity": 25000, "Crew": 6000, "Cargo": 8000,
                                                    "CargoSpaceReserved": 0, "ShipPacks": 0, "ModulePacks": 0,
                                                    "FreeSpace": 11000}},
                  {"timestamp": "2026-11-01T09:32:00Z", "event": "CarrierLocation", "CarrierID": 77,
                   "StarSystem": "Demo Home", "BodyID": 0}]
        with open(os.path.join(cls.jd, "Journal.2026-11-01T090000.01.log"), "w", encoding="utf-8") as fh:
            fh.write("".join(json.dumps(x) + "\n" for x in lines))
        cls.cfg.journal_dir = cls.jd
        cls.app = App(cls.cfg, live=fed_tracker(cls.tmp), db=cls.db)
        cls.app.jumpplans = jumpplan.PlanStore(os.path.join(cls.jd, "jump_plan.json"))
        cls.app._edd_stars = False          # never the real EDDiscovery file in a test
        cls.srv = make_server(cls.app, host="127.0.0.1", port=0)
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def _post(self, path, body, headers=None):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), method="POST",
                                     headers=dict({"Content-Type": "application/json"}, **(headers or {})))
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            out = (e.code, json.loads(e.read() or b"{}"))
            e.close()
            return out

    def _get(self):
        with urllib.request.urlopen(self.base + "/api/jumpplan", timeout=10) as r:
            return json.loads(r.read())

    def test_plan_tick_and_clear(self):
        w = {"X-FIS-Settings": "1"}
        self.assertEqual(self._post("/api/jumpplan/plan", {"name": "Demo 14"})[0], 403)     # no header
        code, res = self._post("/api/jumpplan/plan", {"name": "Nowhere"}, w)
        self.assertEqual((code, res["spansh"]), (404, True))
        self.assertTrue(self._post("/api/jumpplan/plan", {"name": "Demo Home"}, w)[1]["here"])
        code, res = self._post("/api/jumpplan/plan", {"name": "Demo 14", "body": "Demo 14 A 1"}, w)
        self.assertEqual(code, 200)
        self.assertEqual([h["name"] for h in res["plan"]["hops"]], ["Demo 5", "Demo 10", "Demo 14"])
        g = self._get()
        self.assertEqual(g["carrier"]["used"], 14000)       # Spansh's "used capacity"
        self.assertFalse(g["edd"])
        self.assertEqual([r["name"] for r in g["rows"]], ["Demo 5", "Demo 10", "Demo 14"])
        self.assertTrue(g["rows"][0]["next"])
        self.assertEqual(g["plan"]["target"]["body"], "Demo 14 A 1")
        code, res = self._post("/api/jumpplan/import", {"text": json.dumps(SPANSH_JSON)}, w)
        self.assertEqual((code, res["plan"]["source"], res["other_start"]), (200, "spansh", False))
        g = self._get()
        self.assertEqual([r["spansh_fuel"] for r in g["rows"]], [113, 90])
        self.assertEqual(g["spansh"]["destination"], "Demo 9")
        self.assertEqual(self._post("/api/jumpplan/import", {"text": "nonsense"}, w)[0], 400)
        big = {"text": json.dumps(SPANSH_JSON) + " " * 20000}       # larger than 4 KiB: allowed here
        self.assertEqual(self._post("/api/jumpplan/import", big, w)[0], 200)
        self.assertEqual(self._post("/api/jumpplan/clear", {}, w)[0], 200)
        self.assertIsNone(self._get()["plan"])


if __name__ == "__main__":
    unittest.main()
