# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""SV1 (5.1.0): the FIS reads the game's netLog with the plugin's
netstatus.py from its watchdog loop, only while the game runs, and the ship
bar shows GAME SERVER while the connection is troubled."""

import os
import tempfile
import unittest
from unittest import mock

from fis.data import Database
from fis.server import App
from tests.fixtures import make_db
from tests.test_api import fed_tracker, make_cfg

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
SILENT = ("{08:0%d:00GMT 1.0s} First packet received from 1 x 8 [0/2]((10.0.0.1:1))EDServer#1 for a while (25.0s)")


class NetCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        db = make_db(os.path.join(self.tmp, "t.sqlite"))
        self.app = App(make_cfg(db, self.tmp), live=fed_tracker(self.tmp), db=Database(db))
        self.logs = os.path.join(self.tmp, "Logs")
        os.makedirs(self.logs)
        with open(os.path.join(self.logs, "netLog.2026-11-23T090000.01.log"), "w", encoding="utf-8") as fh:
            fh.write("===\n" + "\n".join(SILENT % i for i in range(1, 4)) + "\n")

    def test_troubled_then_game_closed(self):
        ns = self.app.model._optional("netstatus")
        with mock.patch.object(ns, "find_logs_dir", return_value=(self.logs, True)):
            self.app.net_check(now=1000.0)
        self.assertEqual(self.app.net_state["state"], "trouble")
        self.assertEqual(self.app.net_state["count"], 3)
        with mock.patch.object(ns, "find_logs_dir", return_value=(None, False)):
            self.app.net_check(now=1010.0)
            self.assertEqual(self.app.net_state["state"], "trouble", "asked again only after 15 s")
            self.app.net_check(now=1020.0)
        self.assertIsNone(self.app.net_state, "the game not running: nothing to say")

    def test_ship_bar(self):
        with open(os.path.join(WEB, "index.html"), encoding="utf-8") as fh:
            self.assertIn('id="sb-server"', fh.read())
        with open(os.path.join(WEB, "js", "app.js"), encoding="utf-8") as fh:
            js = fh.read()
        self.assertIn("renderServer(s.server);", js)
        self.assertIn('t("GAME SERVER: connection problems since {t}"', js)


if __name__ == "__main__":
    unittest.main()
