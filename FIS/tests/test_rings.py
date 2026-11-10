# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""F4 + E11: ring hotspots in PLANET INFO, per ring.

The journal (SAASignalsFound) gives each ring its own BodyID; the plugin
stores hotspots under that ring id with the ring's name. PLANET INFO of the
ringed planet must find them by the ring names and list them per ring."""

import os
import sqlite3
import tempfile
import unittest

from fis.data import Database

from . import fixtures as fx
from .test_api import make_cfg

RING_A = fx.SYS + " 2 A Ring"


class TestRingHotspots(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="fis-rings-")
        path = fx.make_db(os.path.join(cls.tmp, "db.sqlite"))
        cx = sqlite3.connect(path)
        rows = [(fx.SYS_ID, 30, RING_A, "Tritium", "Tritium", 2),
                (fx.SYS_ID, 30, RING_A, "Platinum", "Platinum", 1),
                # another body's ring in the same system - must not show up
                (fx.SYS_ID, 31, fx.SYS + " 9 A Ring", "Painite", "Painite", 3)]
        cx.executemany("INSERT INTO hotspots(sys_id64, body_id, body_name, material, label, count,"
                       " ring_class, found) VALUES (?,?,?,?,?,?,'Icy','2026-11-10')", rows)
        cx.commit()
        cx.close()
        make_cfg(path, cls.tmp)          # puts the plugin modules on the path
        cls.db = Database(path)
        from fis import model
        cls.model = model

    def test_planet_finds_hotspots_of_its_rings(self):
        b = self.model.build_body(self.db, fx.SYS_ID, 3)
        got = sorted((h["material"], h["count"], h["ring"]) for h in b["hotspots"])
        self.assertEqual(got, [("Platinum", 1, RING_A), ("Tritium", 2, RING_A)])

    def test_hotspots_listed_under_their_ring(self):
        b = self.model.build_body(self.db, fx.SYS_ID, 3)
        ring = b["rings"][0]
        self.assertEqual(ring["name"], RING_A)
        self.assertEqual(sorted((h["material"], h["count"]) for h in ring["hotspots"]),
                         [("Platinum", 1), ("Tritium", 2)])

    def test_body_without_rings_has_none(self):
        b = self.model.build_body(self.db, fx.SYS_ID, 1)
        self.assertEqual(b["hotspots"], [])


if __name__ == "__main__":
    unittest.main()
