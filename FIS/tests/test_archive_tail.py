# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""A5 (5.1.0): the archive reads only the new lines of a growing journal,
outside its lock; a shrunk or rewritten file is read whole."""

import json
import os
import shutil
import tempfile
import time
import unittest

from fis.fleet import Archive

NL = b"\r\n"


def line(ts, ev, **kw):
    return json.dumps(dict({"timestamp": ts, "event": ev}, **kw)).encode() + NL


HEAD = line("2026-11-24T10:00:00Z", "Fileheader", part=1) + line("2026-11-24T10:00:01Z", "Commander", FID="F1", Name="A")


class ArchiveTailTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "Journal.2026-11-24T100000.01.log")
        self.t = time.time()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, data, mode="wb"):
        with open(self.path, mode) as fh:
            fh.write(data)
        self.t += 10
        os.utime(self.path, (self.t, self.t))

    def events(self, ar):
        return ar._files[self.path][1]

    def test_growing_file_read_in_parts(self):
        ar = Archive(self.dir)
        body = b"".join(line("2026-11-24T10:%02d:00Z" % i, "Loadout", Ship="s%d" % i, ShipID=i) for i in range(1, 9))
        self.write(HEAD + body[:150])                     # the last line cut in the middle
        ar.refresh(force=True)
        first = list(self.events(ar))
        self.assertTrue(all(e.get("Ship") != "s9" for e in first))
        reads = []
        real = Archive._read_from
        Archive._read_from = staticmethod(lambda p, start, fid: reads.append(start) or real(p, start, fid))
        try:
            self.write(HEAD + body)
            ar.refresh(force=True)
        finally:
            Archive._read_from = staticmethod(real)
        self.assertEqual(len(reads), 1)
        self.assertGreater(reads[0], 0, "only the new part was read")
        self.assertEqual(self.events(ar), Archive._read(self.path))
        self.assertEqual([e["Ship"] for e in self.events(ar) if e["event"] == "Loadout"], ["s%d" % i for i in range(1, 9)])
        self.assertTrue(all(e["_fid"] == "F1" for e in self.events(ar)), "the commander carries over")

    def test_last_line_without_newline_yet(self):
        ar = Archive(self.dir)
        self.write(HEAD + line("2026-11-24T10:01:00Z", "Loadout", Ship="a", ShipID=1)[:-2])   # whole JSON, no newline
        ar.refresh(force=True)
        self.assertEqual([e.get("Ship") for e in self.events(ar) if e["event"] == "Loadout"], ["a"])
        self.write(NL + line("2026-11-24T10:02:00Z", "Loadout", Ship="b", ShipID=2), "ab")
        ar.refresh(force=True)
        self.assertEqual([e.get("Ship") for e in self.events(ar) if e["event"] == "Loadout"], ["a", "b"])

    def test_shrunk_or_rewritten_file_read_whole(self):
        ar = Archive(self.dir)
        self.write(HEAD + line("2026-11-24T10:01:00Z", "Loadout", Ship="old", ShipID=1))
        ar.refresh(force=True)
        self.write(HEAD[:40])                              # shrunk
        ar.refresh(force=True)
        self.assertEqual(self.events(ar), Archive._read(self.path))
        other = (line("2026-11-24T11:00:00Z", "Fileheader", part=2)
                 + line("2026-11-24T11:00:01Z", "Commander", FID="F2", Name="B"))
        self.write(other + line("2026-11-24T11:01:00Z", "Loadout", Ship="new", ShipID=2) * 3)   # rewritten, longer
        ar.refresh(force=True)
        self.assertEqual(self.events(ar), Archive._read(self.path))
        self.assertEqual({e["_fid"] for e in self.events(ar)}, {"F2"})

    def test_lock_not_held_while_reading(self):
        """Readers (events()) are not held up while a refresh reads a file."""
        ar = Archive(self.dir)
        self.write(HEAD)
        held = []
        real = Archive._read_from
        Archive._read_from = staticmethod(lambda p, s, f: held.append(ar._lock.locked()) or real(p, s, f))
        try:
            ar.refresh(force=True)
        finally:
            Archive._read_from = staticmethod(real)
        self.assertEqual(held, [False])


if __name__ == "__main__":
    unittest.main()
