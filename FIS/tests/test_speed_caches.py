# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""5.1.0 OP1/OP2: what the FIS keeps between answers - fleet() and carrier()
per journal state (each caller its own copy), one event list per commander
view, the mining passes of one answer, the live reader's journal list."""

import os
import tempfile
import time
import unittest

from fis import fleet as fl
from fis import mining
from fis.live import Hub, LiveTracker

from tests.test_fleet import _write_journals


class ArchiveCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        _write_journals(self.tmp.name)
        self.ar = fl.Archive(self.tmp.name)
        self.ar.refresh(force=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_fleet_built_once_per_journal_state_each_caller_a_copy(self):
        calls = []
        real = self.ar._fleet
        self.ar._fleet = lambda: calls.append(1) or real()
        a, b = self.ar.fleet(), self.ar.fleet()
        self.assertEqual(len(calls), 1, "the second answer from the cache")
        self.assertEqual(a, b)
        a["ships"] = "changed by one caller"
        self.assertNotEqual(self.ar.fleet().get("ships"), "changed by one caller", "a copy each")
        self.ar.rev += 1                                    # the journals moved
        self.ar.fleet()
        self.assertEqual(len(calls), 2)

    def test_two_commander_views_kept_side_by_side(self):
        mine, every = self.ar.events(), self.ar.events(fl.ALL_COMMANDERS)
        self.assertEqual(len(self.ar._evcache), 2, "own and all commanders no longer push each other out")
        self.assertEqual(self.ar.events(), mine)
        self.assertEqual(self.ar.events(fl.ALL_COMMANDERS), every)
        self.ar.rev += 1
        self.ar.events()
        self.assertEqual(len(self.ar._evcache), 1, "an older state is dropped")


class MiningMemoTest(unittest.TestCase):
    def test_one_cut_per_list(self):
        evs = [{"event": "ProspectedAsteroid", "timestamp": "2026-11-01T10:00:00Z", "Materials": []},
               {"event": "MiningRefined", "timestamp": "2026-11-01T10:01:00Z", "Type": "$tritium_name;"}]
        r1 = mining._runs(evs)
        self.assertIs(mining._runs(evs), r1, "the same list: the same runs")
        other = list(evs)
        self.assertIsNot(mining._runs(other), r1, "another list is cut again")
        self.assertEqual(mining._runs(other), r1)


class JournalListTest(unittest.TestCase):
    def test_listed_again_only_when_the_folder_changed(self):
        with tempfile.TemporaryDirectory() as d:
            for n in ("Journal.2026-11-01T100000.01.log", "Journal.2026-11-02T100000.01.log"):
                with open(os.path.join(d, n), "w", encoding="utf-8") as fh:
                    fh.write("")
                time.sleep(0.02)
            lt = LiveTracker(d, Hub())
            first = lt.journals()
            self.assertEqual([os.path.basename(p) for p in first],
                             ["Journal.2026-11-01T100000.01.log", "Journal.2026-11-02T100000.01.log"])
            self.assertEqual(lt.journals(), first)
            time.sleep(0.02)
            with open(os.path.join(d, "Journal.2026-11-03T100000.01.log"), "w", encoding="utf-8") as fh:
                fh.write("")
            os.utime(d, None)                                   # some file systems are coarse
            self.assertEqual(len(lt.journals()), 3, "a new journal is seen")


if __name__ == "__main__":
    unittest.main()
