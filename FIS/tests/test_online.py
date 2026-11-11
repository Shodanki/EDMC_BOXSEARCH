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
             "system_x": 1.0, "system_y": 2.0, "system_z": 3.0}
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


if __name__ == "__main__":
    unittest.main()
