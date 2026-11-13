# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""K5: a favourite's position at Spansh - one request on a click, no network here."""

import json
import os
import tempfile
import unittest

from tests import fixtures as fx

from fis.config import Config
from fis.favourites import FavouriteStore
from fis.online import CACHE_S, CarrierLookup

ROW_EXACT = {"name": "K7Q-12Z", "type": "Drake-Class Carrier", "system_name": "Test System",
             "system_id64": 42, "market_id": 555, "updated_at": "2026-11-09T10:00:00Z",
             "system_x": 1.0, "system_y": 2.0, "system_z": 3.0, "carrier_docking_access": "all"}
ROW_OTHER = dict(ROW_EXACT, name="ABC-K7Q", system_name="Elsewhere")      # token match only


class FakeResp:
    def __init__(self, status, body):
        self.status_code, self.headers, self._b = status, {}, body

    def json(self):
        return self._b


class FakeSession:
    sent = []
    answer = (200, {"results": [ROW_OTHER, ROW_EXACT]})

    def __init__(self):
        self.headers = {}

    def request(self, method, url, **kw):
        FakeSession.sent.append((method, url, kw.get("json"), dict(self.headers)))
        return FakeResp(*FakeSession.answer)


class TestOnline(unittest.TestCase):
    def setUp(self):
        cfg = Config()
        cfg.plugin_dir = fx.PLUGIN_DIR
        cfg.use_plugin_path()
        FakeSession.sent = []
        FakeSession.answer = (200, {"results": [ROW_OTHER, ROW_EXACT]})
        self.now = 1794300000.0
        self.offline = False
        self.lk = CarrierLookup("4.7-test", calls_today=lambda: {"spansh": 3},
                                offline=lambda: self.offline, session_factory=FakeSession,
                                clock=lambda: self.now)

    def test_exact_callsign_only(self):
        r = self.lk.lookup("K7Q-12Z")
        self.assertTrue(r["found"])
        self.assertEqual((r["system"], r["pos"], r["updated"]), ("Test System", [1.0, 2.0, 3.0],
                                                                 "2026-11-09T10:00:00Z"))
        self.assertEqual(r["docking_access"], "all")       # A1: from the same answer
        method, url, body, headers = FakeSession.sent[0]
        self.assertEqual((method, url), ("POST", "https://spansh.co.uk/api/stations/search"))
        self.assertEqual(body["filters"]["name"]["value"], "K7Q-12Z")
        self.assertTrue(headers["User-Agent"].startswith("SHBOXSEARCH/"))
        FakeSession.answer = (200, {"results": [ROW_OTHER]})
        self.assertFalse(self.lk.lookup("K7Q-12Z")["found"])       # a token match is not it

    def test_offline_and_errors(self):
        self.offline = True
        self.assertEqual(self.lk.lookup("K7Q-12Z"), {"error": "offline"})
        self.assertEqual(FakeSession.sent, [])
        self.offline = False
        FakeSession.answer = (404, {})
        self.assertIn("404", self.lk.lookup("K7Q-12Z")["error"])

    def test_daily_cap_is_shared_with_the_plugin(self):
        self.lk = CarrierLookup("4.7-test", calls_today=lambda: {"spansh": 50},
                                offline=lambda: False, session_factory=FakeSession,
                                clock=lambda: self.now)
        self.assertIn("error", self.lk.lookup("K7Q-12Z"))
        self.assertEqual(FakeSession.sent, [])

    def test_cache_and_store(self):
        d = tempfile.mkdtemp()
        st = FavouriteStore(os.path.join(d, "favourites.json"))
        st.set_favourite("F1", "K7Q-12Z", True)
        res = self.lk.lookup("K7Q-12Z")
        res["checked"] = "2026-11-11T08:00:00Z"
        self.assertTrue(st.set_online("F1", "K7Q-12Z", res))
        fav = st.get("F1")["favourites"]["K7Q-12Z"]
        self.assertEqual(fav["online"]["system"], "Test System")
        self.now = 1794384000.0 + 3600                  # 1 h after "checked"
        self.assertIsNotNone(self.lk.cached(fav))
        self.now = 1794384000.0 + CACHE_S + 60
        self.assertIsNone(self.lk.cached(fav))
        self.assertFalse(st.set_online("F1", "NOT-AFAV", res))      # only favourites
        with open(os.path.join(d, "favourites.json"), encoding="utf-8") as fh:
            self.assertIn("Test System", json.load(fh)["commanders"]["F1"]["favourites"]["K7Q-12Z"]["online"]["system"])


NEAR = [  # as Spansh answered the one test query of 13.11.2026 (around Sol), shortened
    {"name": "JFM-21Z", "type": "Drake-Class Carrier", "system_name": "Alpha Centauri", "system_id64": 7,
     "system_x": 3.0, "system_y": 0.0, "system_z": 4.0, "updated_at": "2026-11-12T17:12:02Z",
     "carrier_docking_access": "Squadron Friends", "distance": 5.0,
     "services": [{"name": "Dock"}, {"name": "Refuel"}, {"name": "Repair"}, {"name": "Restock"},
                  {"name": "Universal Cartographics"}, {"name": "Crew Lounge"}]},
    {"name": "G6M-8QZ", "type": "Drake-Class Carrier", "system_name": "Barnard's Star", "system_id64": 8,
     "system_x": 1.0, "system_y": 0.0, "system_z": 0.0, "updated_at": "2026-10-01T14:44:09Z",
     "carrier_docking_access": None, "distance": 1.0, "services": [{"name": "Market"}]},
    {"name": "", "system_x": None},                                     # broken row: left out
]


class TestNearby(unittest.TestCase):
    """H2 (4.12): carriers near you - one request per region and day, on a click."""

    def setUp(self):
        cfg = Config()
        cfg.plugin_dir = fx.PLUGIN_DIR
        cfg.use_plugin_path()
        FakeSession.sent = []
        FakeSession.answer = (200, {"results": NEAR})
        self.now = 1794300000.0
        self.offline = False
        self.calls = {"spansh": 3}
        self.lk = CarrierLookup("4.12-test", calls_today=lambda: self.calls,
                                offline=lambda: self.offline, session_factory=FakeSession,
                                clock=lambda: self.now)

    def test_request_and_answer(self):
        r = self.lk.nearby([0.0, 0.0, 0.0])
        method, url, body, _h = FakeSession.sent[0]
        self.assertEqual((method, url), ("POST", "https://spansh.co.uk/api/stations/search"))
        self.assertEqual(body["filters"]["type"]["value"], ["Drake-Class Carrier"])
        self.assertEqual(body["filters"]["distance"], {"min": "0", "max": "100"})
        self.assertEqual(body["reference_coords"], {"x": 0.0, "y": 0.0, "z": 0.0})
        self.assertEqual(body["sort"], [{"distance": {"direction": "asc"}}])
        self.assertFalse(r["cached"])
        self.assertEqual([c["callsign"] for c in r["carriers"]], ["G6M-8QZ", "JFM-21Z"])   # nearest first
        jfm = r["carriers"][1]
        self.assertEqual(jfm["distance"], 5.0)
        self.assertEqual(jfm["services"], ["exploration", "rearm", "refuel", "repair"])
        self.assertEqual((jfm["access"], jfm["system"], jfm["updated"]),
                         ("Squadron Friends", "Alpha Centauri", "2026-11-12T17:12:02Z"))

    def test_one_request_per_region_and_day(self):
        self.lk.nearby([0.0, 0.0, 0.0])
        r = self.lk.nearby([10.0, 0.0, 0.0])            # same 50-ly cell: nothing asked
        self.assertEqual(len(FakeSession.sent), 1)
        self.assertTrue(r["cached"])
        # distances from where you are now - the order turns around
        self.assertEqual([(c["callsign"], c["distance"]) for c in r["carriers"]],
                         [("JFM-21Z", 8.06), ("G6M-8QZ", 9.0)])
        self.lk.nearby([60.0, 0.0, 0.0])                 # another cell: asked
        self.assertEqual(len(FakeSession.sent), 2)
        self.now += 24 * 3600 + 60                       # a day later: asked again
        self.lk.nearby([0.0, 0.0, 0.0])
        self.assertEqual(len(FakeSession.sent), 3)

    def test_starred_from_the_list_keeps_its_place(self):
        self.assertIsNone(self.lk.from_nearby("JFM-21Z"))
        self.lk.nearby([0.0, 0.0, 0.0])
        on = self.lk.from_nearby("JFM-21Z")
        self.assertEqual((on["found"], on["system"], on["pos"], on["docking_access"]),
                         (True, "Alpha Centauri", [3.0, 0.0, 4.0], "Squadron Friends"))
        self.assertIsNone(self.lk.from_nearby("NOT-HERE"))
        self.now += 24 * 3600 + 60                       # an old answer is not used
        self.assertIsNone(self.lk.from_nearby("JFM-21Z"))
        self.assertEqual(len(FakeSession.sent), 1)       # nothing asked for any of this

    def test_offline_cap_and_errors(self):
        self.offline = True
        self.assertEqual(self.lk.nearby([0.0, 0.0, 0.0]), {"error": "offline"})
        self.offline = False
        self.calls = {"spansh": 50}                      # the plugin used today's 50
        self.assertIn("error", self.lk.nearby([0.0, 0.0, 0.0]))
        self.assertEqual(FakeSession.sent, [])
        self.calls = {"spansh": 3}
        lk = CarrierLookup("4.12-test", calls_today=lambda: self.calls, offline=lambda: False,
                           session_factory=FakeSession, clock=lambda: self.now)
        FakeSession.answer = (500, {})
        self.assertIn("500", lk.nearby([0.0, 0.0, 0.0])["error"])


if __name__ == "__main__":
    unittest.main()
