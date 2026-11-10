# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""K2: carrier favourites - the store, the API and its locks (invented names)."""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from fis.favourites import FavouriteStore, MAX_NOTE
from fis.server import App, make_server
from tests.test_api import _Base, fed_tracker
from tests.test_carriers import EVS


def _journal(d, fid="F7", name="Tester"):
    lines = [{"timestamp": "2026-11-01T09:00:00Z", "event": "Commander", "FID": fid, "Name": name}] + EVS
    with open(os.path.join(d, "Journal.2026-11-01T090000.01.log"), "w", encoding="utf-8") as fh:
        fh.write("".join(json.dumps(x) + "\n" for x in lines))


class TestStore(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.path = os.path.join(self.d, "favourites.json")

    def test_star_note_unstar_per_commander(self):
        st = FavouriteStore(self.path)
        f = st.set_favourite("F1", "Q2W-3ER", True, note="tritium\nrun " + "x" * 300,
                             info={"system": "Test Beta", "ts": "2026-11-01T10:30:00Z", "pos": [1, 2, 3]})
        self.assertEqual(len(f["note"]), MAX_NOTE)
        self.assertNotIn("\n", f["note"])
        # another commander has his own list; a new store reads the file
        self.assertEqual(FavouriteStore(self.path).get("F2")["favourites"], {})
        got = FavouriteStore(self.path).get("F1")["favourites"]["Q2W-3ER"]
        self.assertEqual((got["system"], got["pos"]), ("Test Beta", [1, 2, 3]))
        self.assertIsNone(st.set_favourite("F1", "Q2W-3ER", False))
        self.assertEqual(FavouriteStore(self.path).get("F1")["favourites"], {})
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    def test_bad_input(self):
        st = FavouriteStore(self.path)
        for cs in ("", "Q2W3ER", "../x", "q2w-3er"):
            with self.assertRaises(ValueError):
                st.set_favourite("F1", cs, True)

    def test_broken_file_is_kept_aside(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        st = FavouriteStore(self.path)
        self.assertEqual(st.get("F1")["favourites"], {})
        self.assertTrue(os.path.exists(self.path + ".bad"))

    def test_position_only_moves_forward(self):
        st = FavouriteStore(self.path)
        st.set_favourite("F1", "Q2W-3ER", True, info={"system": "A", "ts": "2026-11-02T00:00:00Z"})
        self.assertFalse(st.remember_position("F1", "Q2W-3ER", {"system": "Old", "ts": "2026-11-01T00:00:00Z"}))
        self.assertTrue(st.remember_position("F1", "Q2W-3ER", {"system": "New", "ts": "2026-11-03T00:00:00Z"}))
        self.assertEqual(st.get("F1")["favourites"]["Q2W-3ER"]["system"], "New")


class TestApi(_Base):
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
        cls.app.favourites = FavouriteStore(os.path.join(cls.jd, "favourites.json"))
        cls.srv = make_server(cls.app, host="127.0.0.1", port=0)
        cls.port = cls.srv.server_address[1]
        cls.base = "http://127.0.0.1:%d" % cls.port
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.cfg.lan = False

    def _post(self, body, headers):
        req = urllib.request.Request(self.base + "/api/carriers/favourite", data=json.dumps(body).encode(),
                                     headers=dict({"Content-Type": "application/json"}, **headers), method="POST")
        return urllib.request.urlopen(req, timeout=5)

    def _code(self, body, headers):
        try:
            with self._post(body, headers) as r:
                return r.status
        except urllib.error.HTTPError as e:
            e.close()
            return e.code

    def _known(self, headers=None):
        req = urllib.request.Request(self.base + "/api/carriers/known", headers=headers or {})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())


class TestApiLocal(TestApi):
    def test_locks(self):
        star = {"callsign": "Q2W-3ER", "on": True}
        self.assertEqual(self._code(star, {}), 403)                                        # no header
        self.assertEqual(self._code(star, {"X-FIS-Settings": "1", "Origin": "http://evil.example"}), 403)
        # DNS rebinding: a foreign name pointing at 127.0.0.1 - same "origin", wrong host
        self.assertEqual(self._code(star, {"X-FIS-Settings": "1", "Host": "evil.example:%d" % self.port,
                                           "Origin": "http://evil.example:%d" % self.port}), 403)
        self.assertEqual(self._code({"callsign": "nope"}, {"X-FIS-Settings": "1"}), 400)

    def test_star_and_list(self):
        k = self._known()
        self.assertEqual(k["commander"], "Tester")
        self.assertEqual([i["callsign"] for i in k["met"]], ["Q2W-3ER"])
        with self._post({"callsign": "Q2W-3ER", "on": True, "note": "gold run"},
                        {"X-FIS-Settings": "1", "Origin": self.base}) as r:
            self.assertTrue(json.loads(r.read())["favourite"])
        k = self._known()
        self.assertEqual([i["callsign"] for i in k["favourites"]], ["Q2W-3ER"])
        f = k["favourites"][0]
        self.assertEqual((f["note"], f["system"], f["favourite"], f["name"]), ("gold run", "Test Beta", True, "BLUE HERON"))
        self.assertEqual(k["met"], [])
        # a favourite the journal no longer has keeps its stored position
        stored = self.app.favourites.get("F7")["favourites"]["Q2W-3ER"]
        self.assertEqual(stored["system"], "Test Beta")
        # SYSTEM points of interest: the star travels with the system data
        out = self.app._with_favourites({"poi": [{"kind": "carrier", "name": "BLUE HERON Q2W-3ER"}]})
        self.assertTrue(out["poi"][0]["favourite"])
        with self._post({"callsign": "Q2W-3ER", "on": False}, {"X-FIS-Settings": "1"}) as r:
            self.assertFalse(json.loads(r.read())["favourite"])


class TestMarketSnapshot(TestApi):
    def test_k3_market_of_a_visited_carrier(self):
        from tests.test_visiting import TRIT, GOLD, _market
        m = _market(4711, [TRIT, GOLD])
        m["StationName"], m["timestamp"] = "Q2W-3ER", "2026-11-01T12:00:30Z"
        with open(os.path.join(self.jd, "Market.json"), "w", encoding="utf-8") as fh:
            json.dump(m, fh)
        docked = {"status": {"flags": 1}}
        # the journal ends docked at the own carrier: that market is not the
        # last docking -> nothing kept; once the archive says we are docked
        # there, it is
        self.assertFalse(self.app.snapshot_market(docked))
        with open(os.path.join(self.jd, "Journal.2026-11-01T120000.01.log"), "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"timestamp": "2026-11-01T12:00:00Z", "event": "Docked", "StationName": "Q2W-3ER",
                                 "StationType": "FleetCarrier", "MarketID": 4711, "StarSystem": "Test Alpha",
                                 "SystemAddress": 1}) + "\n")
        self.app.archive.refresh(force=True)
        self.assertTrue(self.app.snapshot_market(docked))
        self.assertFalse(self.app.snapshot_market(docked))                  # nothing new
        snap = self.app.favourites.get("F7")["markets"]["Q2W-3ER"]
        self.assertEqual(([b["key"] for b in snap["buys"]], [s["key"] for s in snap["sells"]]),
                         (["tritium"], ["gold"]))
        self.assertEqual(self._known()["met"][0]["market"]["ts"], "2026-11-01T12:00:30Z")

    def test_k3_older_market_never_replaces(self):
        st = self.app.favourites
        self.assertTrue(st.note_market("F9", {"callsign": "A1A-1AA", "market_ts": "2026-11-02T00:00:00Z",
                                              "buys": [], "sells": []}))
        self.assertFalse(st.note_market("F9", {"callsign": "A1A-1AA", "market_ts": "2026-11-01T00:00:00Z",
                                               "buys": [], "sells": []}))


class TestApiLan(TestApi):
    lan = True

    def test_tablet_needs_the_token(self):
        star = {"callsign": "Q2W-3ER", "on": True}
        self.assertEqual(self._code(star, {"X-FIS-Settings": "1"}), 403)
        self.assertEqual(self._code(star, {"X-FIS-Settings": "1", "X-FIS-Token": "wrong"}), 403)
        self.assertEqual(self._code(star, {"X-FIS-Settings": "1", "X-FIS-Token": "secret-token"}), 200)
        self.assertEqual(self._code(star, {"X-FIS-Settings": "1", "Cookie": "fis_token=secret-token"}), 200)
        k = self._known({"X-FIS-Token": "secret-token"})
        self.assertEqual(k["counts"]["favourites"], 1)


del TestApi

if __name__ == "__main__":
    unittest.main()
