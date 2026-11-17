# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""SK3: LEARNING STATUS shows the route, work and fuel models with what they
learnt from, and each can be reset (FIS/learn_reset.json, next to fis.ini)."""

import calendar
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

from fis import calib
from fis import learn
from fis.live import LiveTracker
from fis.server import App, make_server
from tests.test_api import _Base


def _e(t, ev, **kw):
    return dict({"timestamp": "2026-11-17T%sZ" % t, "event": ev}, **kw)


def _ship_events():
    """A ship with mass and five jumps (fuel model fitted with the mass)."""
    out = [_e("10:00:00", "Commander", FID="F1", Name="Main"),
           _e("10:00:01", "Loadout", Ship="panthermkii", ShipID=9, MaxJumpRange=30.0, UnladenMass=1857.0,
              FuelCapacity={"Main": 64.0, "Reserve": 1.0},
              Modules=[{"Slot": "FrameShiftDrive", "Item": "int_hyperdrive_overcharge_size7_class5"}])]
    for i, d in enumerate((14.0, 18.0, 22.0, 26.0, 30.0)):
        used = 1.2e-12 * (d * 1921.0) ** 2.75
        out.append(_e("10:%02d:00" % (i + 1), "FSDJump", StarSystem="S%d" % i, SystemAddress=100 + i,
                      StarPos=[0, 0, i], JumpDist=d, FuelUsed=used, FuelLevel=64.0 - used))
    return out


class TestModelStatus(_Base):
    def test_models_in_the_learning_status(self):
        lt = LiveTracker(".")
        for e in _ship_events():
            lt.feed(e)
        sr = self.model.plugin().sysroute
        info = {"measured": {"sc": 12, "dss": 7, "bio": 2}, "since": {"route": 1763380000.0, "work": None}}
        m = learn.model_status(info, lt.snapshot(), sr.DEFAULT_MODEL)
        self.assertEqual(m["route"]["measured"], 12)
        self.assertFalse(m["route"]["calibrated"])
        self.assertEqual(m["route"]["since"], 1763380000.0)
        self.assertEqual((m["work"]["dss_n"], m["work"]["bio_n"], m["work"]["since"]), (7, 2, None))
        f = m["fuel"]
        self.assertEqual((f["source"], f["mass"], f["n"], f["ship"]), ("fit", True, 5, "panthermkii"))

    def test_calibrator_leaves_out_what_came_before_the_reset(self):
        jd = tempfile.mkdtemp(prefix="fis-lr-")
        ev = [{"timestamp": "2026-11-01T10:00:%02dZ" % i, "event": "Music"} for i in range(5)] + \
             [{"timestamp": "2026-11-02T10:00:%02dZ" % i, "event": "Music"} for i in range(3)]
        with open(os.path.join(jd, "Journal.2026-11-01T100000.01.log"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(json.dumps(e) for e in ev) + "\n")
        sr = self.model.plugin().sysroute
        lr = self.model.plugin().learnreset
        cut = float(calendar.timegm((2026, 11, 2, 10, 0, 0)))
        marks = {"work": lr.since({"work": cut}, "work"), "route": None}
        c = calib.Calibrator(jd, sr, marks=lambda: marks)
        c.run_once()
        self.assertEqual(c.info["measured"]["events"], 3)
        self.assertEqual(c.info["since"], {"route": None, "work": cut})
        c2 = calib.Calibrator(jd, sr)
        c2.run_once()
        self.assertEqual(c2.info["measured"]["events"], 8)


class TestResetEndpoint(_Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cfg.ini_path = os.path.join(cls.tmp, "fis.ini")      # the marks go next to it
        cls.cfg.lan, cls.cfg.token = False, ""
        lt = LiveTracker(cls.tmp)
        for e in _ship_events():
            lt.feed(e)
        cls.app = App(cls.cfg, live=lt, db=cls.db)
        cls.srv = make_server(cls.app, host="127.0.0.1", port=0)
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def _post(self, body, headers=None):
        req = urllib.request.Request(self.base + "/api/learning/reset", data=json.dumps(body).encode(),
                                     headers=dict({"Content-Type": "application/json"}, **(headers or {})),
                                     method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            e.close()
            return e.code, None

    def test_reset(self):
        path = os.path.join(self.tmp, "learn_reset.json")
        self.assertEqual(self._post({"part": "route"})[0], 403)            # not from the FIS page
        self.assertEqual(self._post({"part": "x"}, {"X-FIS-Settings": "1"})[0], 400)
        self.assertFalse(os.path.exists(path))
        code, out = self._post({"part": "route"}, {"X-FIS-Settings": "1"})
        self.assertEqual((code, out["part"]), (200, "route"))
        lr = self.model.plugin().learnreset
        self.assertAlmostEqual(lr.load(path)["route"], out["since"], places=3)
        # the fuel model of the current ship: its jumps are forgotten
        self.assertEqual(len(self.app.live_state()["jumps"]), 5)
        code, out = self._post({"part": "fuel"}, {"X-FIS-Settings": "1"})
        self.assertEqual(code, 200)
        self.assertEqual(self.app.live_state()["jumps"], [])
        marks = lr.fuel_since(lr.load(path))
        self.assertEqual(list(marks), [("Main", 9, 37)])
        # an older jump read again (a replay) is not learnt; a new one is
        at = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))      # noqa: E731
        self.app.live.feed({"timestamp": at(out["since"] - 3600), "event": "FSDJump", "StarSystem": "Old",
                            "SystemAddress": 1, "StarPos": [0, 0, 0], "JumpDist": 20.0, "FuelUsed": 2.0,
                            "FuelLevel": 60.0})
        self.assertEqual(self.app.live_state()["jumps"], [])
        self.app.live.feed({"timestamp": at(out["since"] + 60), "event": "FSDJump", "StarSystem": "New",
                            "SystemAddress": 2, "StarPos": [0, 0, 0], "JumpDist": 20.0, "FuelUsed": 2.0,
                            "FuelLevel": 60.0})
        self.assertEqual(len(self.app.live_state()["jumps"]), 1)
        # the statistics carry the models
        with urllib.request.urlopen(self.base + "/api/statistics", timeout=10) as r:
            st = json.loads(r.read())
        self.assertIn("models", st["learning"])
        self.assertEqual(st["learning"]["models"]["fuel"]["n"], 1)


if __name__ == "__main__":
    unittest.main()
