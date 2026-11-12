# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""SHIP -> LOST DATA: hiding crash losses from the list (FIS/lost_hidden.json),
the distance caps and the locks of the write endpoint."""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from fis import losthidden as lh
from fis.losthidden import LostHiddenStore
from fis.server import App, make_server
from tests.test_api import _Base, fed_tracker
from tests.test_favourites import _journal

T1, T2 = "2026-11-07T10:00:00Z", "2026-11-11T19:27:41Z"


def lost(ts_a=T2):
    return [{"id64": 1, "name": "Near", "pos": [0, 0, 50], "ts": ts_a, "scan": 3, "map": 1, "bio": ["Bacterium Cerbrus"] * 2},
            {"id64": 2, "name": "Far", "pos": [0, 0, 300], "ts": T2, "scan": 2, "map": 0, "bio": []},
            {"id64": 3, "name": "Old", "pos": [0, 0, 10], "ts": T1, "scan": 1, "map": 0, "bio": []},
            {"id64": 4, "name": "Nowhere", "pos": None, "ts": T2, "scan": 1, "map": 0, "bio": []}]


class TestFilter(unittest.TestCase):
    def test_sorted_by_day_then_distance(self):
        vis, n = lh.apply(lost(), [], [0, 0, 0])
        self.assertEqual([s["name"] for s in vis], ["Near", "Far", "Nowhere", "Old"])
        self.assertEqual((vis[0]["dist"], vis[1]["dist"], vis[2]["dist"]), (50.0, 300.0, None))
        self.assertEqual(n, 0)

    def test_hide_system_and_items(self):
        hid = [{"id64": 2, "what": None, "ts": T2}, {"id64": 1, "what": "scan", "ts": T2},
               {"id64": 1, "what": "bio:Bacterium Cerbrus", "ts": T2}]
        vis, n = lh.apply(lost(), hid, [0, 0, 0])
        self.assertEqual([s["name"] for s in vis], ["Near", "Nowhere", "Old"])
        near = vis[0]
        self.assertEqual((near["scan"], near["map"], near["bio"]), (0, 1, []))
        self.assertEqual(n, 3)
        # all items hidden: the system is not listed any more
        vis, _ = lh.apply(lost(), hid + [{"id64": 1, "what": "map", "ts": T2}], [0, 0, 0])
        self.assertNotIn("Near", [s["name"] for s in vis])

    def test_a_newer_crash_lists_it_again(self):
        hid = [{"id64": 1, "what": None, "ts": T1}]
        vis, n = lh.apply(lost(ts_a=T2), hid)
        self.assertIn("Near", [s["name"] for s in vis])
        self.assertEqual(n, 0)

    def test_cap(self):
        vis, _ = lh.apply(lost(), [], [0, 0, 0])
        self.assertEqual([s["name"] for s in lh.beyond(vis, 250)], ["Far"])
        self.assertEqual([s["name"] for s in lh.beyond(vis, 1000)], [])   # unknown distance stays
        self.assertEqual(lh.beyond(lh.apply(lost(), [])[0], 100), [])     # no position: nothing

    def test_valid_what(self):
        for w in (None, "scan", "map", "bio:Stratum Tectonicas"):
            self.assertTrue(lh.valid_what(w))
        for w in ("bio:", "x", 3, "bio:" + "a" * 200, "bio:a\nb"):
            self.assertFalse(lh.valid_what(w))


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "lost_hidden.json")
        self.addCleanup(self.tmp.cleanup)

    def test_hide_per_commander_atomic_and_tied_to_the_loss(self):
        st = LostHiddenStore(self.path)
        self.assertEqual(st.hide("F1", [(1, "scan"), (2, None), (99, None), (1, "scan")], lost()), 2)
        self.assertEqual(st.get("F2"), [])
        got = {(h["id64"], h["what"]): h["ts"] for h in st.get("F1")}
        self.assertEqual(got, {(1, "scan"): T2, (2, None): T2})
        self.assertFalse(os.path.exists(self.path + ".tmp"))
        with open(self.path, encoding="utf-8") as fh:
            self.assertIn("F1", json.load(fh)["commanders"])
        # a fresh store reads the file; entries of systems no longer lost are pruned
        st2 = LostHiddenStore(self.path)
        st2.hide("F1", [(3, None)], [s for s in lost() if s["id64"] != 2])
        self.assertEqual({(h["id64"], h["what"]) for h in st2.get("F1")}, {(1, "scan"), (3, None)})
        self.assertEqual(st2.reset("F1"), 2)
        self.assertEqual(st2.get("F1"), [])

    def test_broken_file_is_kept_aside(self):
        with open(self.path, "w") as fh:
            fh.write("{nope")
        self.assertEqual(LostHiddenStore(self.path).get("F1"), [])
        self.assertTrue(os.path.exists(self.path + ".bad"))


class _Api(_Base):
    lan = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.jd = tempfile.mkdtemp()
        _journal(cls.jd)
        cls.cfg.journal_dir = cls.jd
        cls.cfg.lan = cls.lan
        cls.cfg.token = "secret-token" if cls.lan else ""
        cls.app = App(cls.cfg, live=fed_tracker(cls.tmp), db=cls.db)
        cls.app.lost_hidden = LostHiddenStore(os.path.join(cls.jd, "lost_hidden.json"))
        cls.db.lost_summary = lambda fid: lost()          # instance stub, this test only
        cls.srv = make_server(cls.app, host="127.0.0.1", port=0)
        cls.port = cls.srv.server_address[1]
        cls.base = "http://127.0.0.1:%d" % cls.port
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.cfg.lan = False
        del cls.db.lost_summary

    def _code(self, body, headers, raw=None):
        req = urllib.request.Request(self.base + "/api/ship/lost_hidden",
                                     data=raw if raw is not None else json.dumps(body).encode(),
                                     headers=dict({"Content-Type": "application/json"}, **headers), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            e.close()
            return e.code, None


class TestApiLocal(_Api):
    def test_locks(self):
        hide = {"hide": [{"id64": 1, "what": None}]}
        self.assertEqual(self._code(hide, {})[0], 403)
        self.assertEqual(self._code(hide, {"X-FIS-Settings": "1", "Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self._code(hide, {"X-FIS-Settings": "1", "Host": "evil.example:%d" % self.port})[0], 403)
        self.assertEqual(self._code(None, {"X-FIS-Settings": "1"}, raw=b"x" * 5000)[0], 400)
        for bad in ({"hide": [{"id64": "1", "what": None}]}, {"hide": [{"id64": 1, "what": "x"}]},
                    {"hide": []}, {"cap": 333}, {"cap": True}, [1]):
            self.assertEqual(self._code(bad, {"X-FIS-Settings": "1"})[0], 400, bad)
        self.assertEqual(self.app.lost_hidden.get("F7"), [])

    def test_hide_shows_in_shipstatus_and_reset(self):
        h = {"X-FIS-Settings": "1", "Origin": self.base}
        code, out = self._code({"hide": [{"id64": 1, "what": "bio:Bacterium Cerbrus"}, {"id64": 3, "what": None}]}, h)
        self.assertEqual((code, out), (200, {"hidden": 2}))
        from fis import shipview
        live = self.app.live_state()
        s = shipview.build_shipstatus(live, self.app.archive, self.jd, self.app.db, lost_hidden=self.app.lost_hidden)
        U = s["unsold"]
        self.assertIsNotNone(U)
        self.assertEqual(U["lost_hidden"], 2)
        self.assertEqual([x["id64"] for x in U["lost_systems"]], [1, 2, 4])   # all of them, no cap
        self.assertEqual(U["lost_systems"][0]["bio"], [])
        self.assertEqual(U["lost_caps"], [100, 250, 500, 1000])
        code, out = self._code({"reset": True}, h)
        self.assertEqual((code, out), (200, {"shown": 2}))
        self.assertEqual(self.app.lost_hidden.get("F7"), [])

    def test_cap_needs_a_position_and_hides_the_far_ones(self):
        h = {"X-FIS-Settings": "1"}
        pos = (self.app.live_state().get("system") or {}).get("pos")
        code, out = self._code({"cap": 100}, h)
        if not pos:
            self.assertEqual(code, 409)
            return
        vis, _ = lh.apply(lost(), [], pos)
        self.assertEqual((code, out), (200, {"hidden": len(lh.beyond(vis, 100))}))
        self.app.lost_hidden.reset("F7")


class TestApiLan(_Api):
    lan = True

    def test_tablet_needs_the_token(self):
        hide = {"hide": [{"id64": 2, "what": None}]}
        self.assertEqual(self._code(hide, {"X-FIS-Settings": "1"})[0], 403)
        self.assertEqual(self._code(hide, {"X-FIS-Settings": "1", "X-FIS-Token": "wrong"})[0], 403)
        self.assertEqual(self._code(hide, {"X-FIS-Settings": "1", "X-FIS-Token": "secret-token"})[0], 200)
        self.app.lost_hidden.reset("F7")


if __name__ == "__main__":
    unittest.main()
