# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""V0 reality check: each model's error value from what happened."""
import threading
import unittest

from fis import realitycheck as rc
from fis import server


class Fuel:
    """A fuel model that burns 0.01 t per ly x mass/100, learnt or not."""

    def __init__(self, js):
        self.js = js

    def cost_of(self, d, m=None):
        return 0.01 * d * (m or 100.0) / 100.0


class RealityTest(unittest.TestCase):
    def test_fuel_online(self):
        js = [(50.0, 0.5, 100.0)] * 4 + [(50.0, 0.55, 100.0), (40.0, 0.4, 100.0)]
        f = rc.fuel(js, Fuel)
        self.assertEqual(f["n"], 2)                 # only jumps with four before them
        self.assertEqual(f["median_pct"], 9.1)      # 0.5 against 0.55 is 9.1 % off; 0.4 exact
        self.assertIsNone(rc.fuel(js[:4], Fuel))

    def test_kepler_and_finds(self):
        per = {1: {"checked": 10, "ok": 9}, 2: {"checked": 10, "ok": 10}, 3: None}
        k = rc.kepler([1, 2, 3], lambda s: per[s])
        self.assertEqual((k["ok_pct"], k["checked"], k["systems"]), (95.0, 20, 2))
        self.assertIsNone(rc.kepler([1], lambda s: 1 / 0))
        fd = rc.finds({"bands": [{"n": 50, "predicted": 0.03, "rate": 0.05},
                                 {"n": 50, "predicted": 0.19, "rate": 0.18}, {"n": 0}]})
        self.assertEqual((fd["gap_pp"], fd["n"]), (1.5, 100))

    def test_rows(self):
        rows = {r["key"]: r for r in rc.build({
            "kepler": {"ok_pct": 91.7, "checked": 2106, "systems": 202},
            "fuel": {"median_pct": 0.8, "p90_pct": 10.1, "n": 646},
            "route": {"ratio": 2.1, "ratio_n": 12},
            "value": {"factor": 0.91, "lo": 0.75, "hi": 1.29, "n": 12},
            "bio": {"bodies": 104, "recall_top3": 0.76, "top1_right": 0.88}})}
        self.assertTrue(rows["kepler"]["good"] and rows["fuel"]["good"] and rows["value"]["good"])
        self.assertIs(rows["route"]["good"], False)                 # twice the estimate: flagged
        self.assertIsNone(rows["finds"]["value"])
        self.assertIsNone(rows["finds"]["good"])                    # no data: thin, not wrong
        self.assertNotIn("work", rows)
        self.assertIn("76 %", rows["bio"]["value"])

    def test_pending_row(self):
        rows = rc.build({"kepler": {"pending": True}})
        self.assertTrue(rows[0]["pending"])
        self.assertIsNone(rows[0]["value"])
        self.assertNotIn("pending", rc.build({})[0])

    def test_rock_yield_judges_each_rock_by_the_ones_before(self):
        import sys
        from tests.fixtures import PLUGIN_DIR
        if PLUGIN_DIR not in sys.path:
            sys.path.append(PLUGIN_DIR)
        import miningstat

        def rock(share, tonnes):
            head = [{"event": "ProspectedAsteroid", "Materials": [{"Name": "Platinum", "Proportion": share}]}]
            return head + [{"event": "MiningRefined", "Type": "$platinum_name;"}] * tonnes
        evs = []
        for t in (4, 5, 6, 5, 4, 5, 9):              # six rocks learn, the seventh is judged too
            evs += rock(5.0, t)
        evs.append({"event": "Docked"})
        r = rc.rock_yield(evs, miningstat.RockYield)
        self.assertEqual(r["n"], 2)                   # rocks 6 and 7: five before them each
        self.assertEqual(r["inside_pct"], 50.0)       # 5 t inside 4-5, 9 t outside
        self.assertIsNone(rc.rock_yield([], miningstat.RockYield))

    def test_collectors_against_the_learnt_mark(self):
        c = rc.collectors({"ctrl": [300, 310, 290, 305, 295, 300, 900]})
        self.assertEqual((c["n"], c["within_pct"]), (2, 50.0))
        self.assertIsNone(rc.collectors({"ctrl": [300, 310]}))
        rows = {r["key"]: r for r in rc.build({"rocks": {"median_pct": 44.4, "inside_pct": 60.5, "n": 147},
                                               "collectors": {"within_pct": 89.3, "n": 75}})}
        self.assertTrue(rows["rocks"]["good"] and rows["collectors"]["good"])
        self.assertIn("60 % in the middle half", rows["rocks"]["value"])

    def test_double_moons(self):
        LS = 1.0 / 299792458.0

        class B:
            def __init__(self, kind, parent, check=None, sma_ls=None, arrival=None):
                self.kind, self.parent_id, self.check = kind, parent, check
                self.orbit = (sma_ls / LS,) if sma_ls else None
                self.arrival_ls = arrival
        # planet 1 at 2,000 LS is 0.002 LS off - a millionth of its orbit, its own check passes
        bodies = {0: B("Star", None), 1: B("Planet", 0, (1e-6, 1e-6), 2000.0, 2000.0),
                  2: B("BaryCentre", 1),
                  3: B("Planet", 2, (0.002, 0), 0.01, 2000.0),                 # within its own 1 %
                  4: B("Planet", 2, (0.2, 0.002 / 2000.0), 0.01, 2000.0),      # KR2: the planet's error only
                  8: B("Planet", 2, (0.9, 0.0110 / 2000.0), 0.01, 2000.0),     # 0.009 LS beyond: really off
                  5: B("BaryCentre", 0), 6: B("Planet", 5, (0.001, 0)),         # planets round a star pair
                  7: B("Planet", 1, (0.001, 0))}                                # a plain moon
        self.assertEqual(rc.double_moons(bodies, 0.01, LS), {"moons_checked": 3, "moons_ok": 2, "moons_own_ok": 1})
        k = rc.kepler([1, 2], lambda s: {"checked": 10, "ok": 8, "moons_checked": 6, "moons_own_ok": 2,
                                         "moons_ok": 6 if s == 1 else 3})
        self.assertEqual((k["moons_checked"], k["moons_ok_pct"]), (12, 75.0))
        self.assertEqual(k["ok_pct"], 100.0 * (16 + 4 + 1) / 20)                # all bodies count them too
        rows = {r["key"]: r for r in rc.build({"kepler": k})}
        self.assertIs(rows["kepler_moons"]["good"], False)
        self.assertIn("beyond their planet's error", rows["kepler_moons"]["value"])
        self.assertTrue(rc.build({"kepler": {"pending": True}})[1]["pending"])


class _DB:
    def __init__(self):
        self.n = 100

    def one(self, sql, *a):
        return {"n": self.n}


class _Hub:
    def __init__(self):
        self.events = []

    def publish(self, kind, data):
        self.events.append(kind)


class KeplerBackgroundTest(unittest.TestCase):
    """R1: STATISTICS never waits for the Kepler check - it is computed in
    the background and the browsers are told when it is there."""

    def _app(self, compute):
        a = server.App.__new__(server.App)
        a.db, a.hub = _DB(), _Hub()
        a._cache, a._cache_lock = {}, threading.Lock()
        a._kepler_busy, a._kepler_last = False, None
        a._kepler_compute = compute
        return a

    def test_request_does_not_wait(self):
        gate, calls = threading.Event(), []

        def compute(sig):
            calls.append(sig)
            gate.wait(5)
            val = {"ok_pct": 95.0, "checked": 10, "systems": 2}
            a._cache["kepler_check"], a._kepler_last = (sig, val), val
            return val
        a = self._app(compute)
        self.assertEqual(a.kepler_check(), {"pending": True})
        self.assertEqual(a.kepler_check(), {"pending": True})          # second request: no second thread
        gate.set()
        for th in threading.enumerate():
            if th.name == "fis-kepler":
                th.join(5)
        self.assertEqual(calls, [4])
        self.assertEqual(a.kepler_check()["ok_pct"], 95.0)
        self.assertEqual(a.hub.events, ["scan"])
        a.db.n = 125                                                     # 25 more scans: old value while recomputing
        gate.clear()
        self.assertEqual(a.kepler_check()["ok_pct"], 95.0)
        gate.set()

    def test_failure_does_not_loop(self):
        def compute(sig):
            raise RuntimeError("db gone")
        a = self._app(compute)
        a.kepler_check()
        for th in threading.enumerate():
            if th.name == "fis-kepler":
                th.join(5)
        self.assertIsNone(a.kepler_check())


if __name__ == "__main__":
    unittest.main()
