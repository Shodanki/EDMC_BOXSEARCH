# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""NH1 (user 19.11.2026): the next hop where the galaxy map plots no route -
unvisited systems within one jump and the boxels within reach."""

import os
import sqlite3
import tempfile
import unittest

from fis import nexthop
from fis.config import Config
from fis.data import Database
from tests import fixtures as fx


def _live(pos=(100.0, -20.0, 50.0), jump=30.0, name=fx.SYS):
    return {"system": {"name": name, "pos": list(pos) if pos else None}, "ship": {"max_jump": jump}}


class NextHopTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cfg = Config()
        cfg.plugin_dir = fx.PLUGIN_DIR
        cfg.use_plugin_path()
        cls.tmp = tempfile.mkdtemp(prefix="fis-hop-")      # the open database stays (Windows locks it)
        path = fx.make_db(os.path.join(cls.tmp, "db.sqlite"))
        cx = sqlite3.connect(path)
        cx.executemany("INSERT INTO systems (name,id64,x,y,z,quality,star_class,visited,sources) VALUES "
                       "(?,?,?,?,?,?,?,?,?)",
                       [("Testia AB-C d1-9", 1000009, 110.0, -20.0, 50.0, 30, "K", 0, "spansh"),
                        ("Far Away", 1000010, 300.0, -20.0, 50.0, 30, "G", 0, "EDSM"),
                        ("Been There", 1000011, 101.0, -20.0, 50.0, 30, "G", 1, "EDSM")])
        cx.commit()
        cx.close()
        cls.db = Database(path)

    def test_systems_within_one_jump(self):
        out = nexthop.build_nexthop(self.db, _live())
        names = [r["name"] for r in out["rows"]]
        # the current and the visited system are left out, the far one too; one row per system
        self.assertEqual(sorted(names), ["Testia AB-C d1-6", "Testia AB-C d1-9"])
        r9 = next(r for r in out["rows"] if r["name"] == "Testia AB-C d1-9")
        self.assertEqual((r9["ly"], r9["approx"]), (10.0, False))          # a measured position
        self.assertEqual(out["range_ly"], 30.0)
        self.assertEqual(out["total"], 2)
        for r in out["rows"]:
            self.assertIn(r["level"], ("known", "checked", "unchecked", "inhabited"))
        # a shorter range: only the 5 ly neighbour is left
        self.assertEqual([r["name"] for r in nexthop.build_nexthop(self.db, _live(jump=6.0))["rows"]],
                         ["Testia AB-C d1-6"])

    def test_boxels_within_reach_with_search_prefix(self):
        out = nexthop.build_nexthop(self.db, _live(jump=30.0))
        bx = out["boxels"]
        self.assertTrue(bx)
        for b in bx:
            self.assertLessEqual(b["ly"], 30.0)
            self.assertIn(b["mc"], "bcde")
            self.assertTrue(b["prefix"].endswith("-") or b["prefix"][-1].isalpha())
        self.assertLessEqual(len([b for b in bx if b["mc"] == "b"]), nexthop.BOXELS_PER_MC)

    def test_nothing_without_position_or_range(self):
        self.assertEqual(nexthop.build_nexthop(self.db, _live(pos=None))["why"], "no position")
        out = nexthop.build_nexthop(self.db, _live(jump=None))
        self.assertEqual((out["why"], out["rows"]), ("no range", []))


if __name__ == "__main__":
    unittest.main()
