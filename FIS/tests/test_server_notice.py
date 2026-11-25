# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""SV1b (5.1.0, user 25.11.): GAME SERVER in the ship bar when the game wrote
its journal anew - what a lost connection leaves. The game's netLog was
checked first and dropped: its "server silent 20-29 s" lines come about 110
times an hour in every session, the outage day included."""

import os
import tempfile
import unittest

from fis.data import Database
from fis.server import App
from tests.fixtures import make_db
from tests.test_api import fed_tracker, make_cfg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ServerNoticeTest(unittest.TestCase):
    def test_journal_rewrite_shown_for_half_an_hour(self):
        tmp = tempfile.mkdtemp()
        db = make_db(os.path.join(tmp, "t.sqlite"))
        app = App(make_cfg(db, tmp), live=fed_tracker(tmp), db=Database(db))
        self.assertIsNone(app.server_notice(now=1000.0), "no rewrite: nothing")
        app.live.rewrite_ts, app.live.rewrites = 1000.0, 1
        n = app.server_notice(now=1600.0)
        self.assertEqual((n["state"], n["since"], n["count"]), ("rewrite", 1000.0, 1))
        self.assertIsNone(app.server_notice(now=1000.0 + 31 * 60), "half an hour later: gone")

    def test_no_netlog_read_any_more(self):
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(ROOT), "netstatus.py")))
        with open(os.path.join(ROOT, "web", "js", "app.js"), encoding="utf-8") as fh:
            js = fh.read()
        self.assertIn('t("GAME SERVER: journal rewritten {t}"', js)
        with open(os.path.join(ROOT, "fis", "live.py"), encoding="utf-8") as fh:
            self.assertIn("self.rewrite_ts = time.time()", fh.read())


if __name__ == "__main__":
    unittest.main()
