# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""H3 #2: the plugin's plot suggestion (meta "route_corridor") as a corridor
in GALAXY - fresh only, never from a broken entry."""

import json
import sqlite3
import time
import unittest

from fis import galaxy
from tests.test_api import _Base

DOC = {"ts": 0, "half": 12.5, "from": [10.0, 0.0, -5.0],
       "targets": [{"name": "Synuefe AB-C d1", "x": 60.0, "y": 1.0, "z": -40.0, "ly": 61.0,
                    "jumps": 3, "boxels": 14},
                   {"name": "Synuefe XY-Z c2", "x": -30.0, "y": 0.0, "z": 20.0, "ly": 49.0,
                    "jumps": 2, "boxels": 6}]}


class Corridor(_Base):
    def put(self, value):
        cx = sqlite3.connect(self.db_path)
        cx.execute("INSERT OR REPLACE INTO meta(k, v) VALUES ('route_corridor', ?)", (value,))
        cx.commit()
        cx.close()

    def tearDown(self):
        cx = sqlite3.connect(self.db_path)
        cx.execute("DELETE FROM meta WHERE k='route_corridor'")
        cx.commit()
        cx.close()

    def test_fresh_suggestion(self):
        now = time.time()
        self.put(json.dumps(dict(DOC, ts=now - 60)))
        c = galaxy.corridor(self.db, now)
        self.assertEqual(c["from"], {"x": 10.0, "y": 0.0, "z": -5.0})
        self.assertEqual([t["name"] for t in c["targets"]], ["Synuefe AB-C d1", "Synuefe XY-Z c2"])
        self.assertEqual((c["targets"][0]["boxels"], c["targets"][0]["jumps"], c["half"]), (14, 3, 12.5))

    def test_stale_broken_or_empty(self):
        now = time.time()
        self.put(json.dumps(dict(DOC, ts=now - 2 * 86400)))
        self.assertIsNone(galaxy.corridor(self.db, now))           # from somewhere else, long ago
        self.put("{not json")
        self.assertIsNone(galaxy.corridor(self.db, now))
        self.put(json.dumps(dict(DOC, ts=now, targets=[])))
        self.assertIsNone(galaxy.corridor(self.db, now))

    def test_absent(self):
        self.assertIsNone(galaxy.corridor(self.db, time.time()))


if __name__ == "__main__":
    unittest.main()
