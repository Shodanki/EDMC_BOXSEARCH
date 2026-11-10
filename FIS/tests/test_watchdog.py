# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""Live link: a journal the game rewrote under the same name, the reader's watchdog.

06.11.2026: after a lost connection the game started its journal file anew
under the same name. The FIS read on at the old offset, past the new end,
and heard nothing until it was restarted.
"""

import json
import os
import tempfile
import time
import unittest

from fis.live import LiveTracker


def line(ts, event, **kw):
    return json.dumps(dict({"timestamp": "2026-11-06T%sZ" % ts, "event": event}, **kw)) + "\n"


HEAD_A = line("17:23:00", "Fileheader", part=1, gameversion="4.4.2.1")
HEAD_B = line("18:21:59", "Fileheader", part=1, gameversion="4.4.2.1")


class RewriteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "Journal.2026-11-06T182300.01.log")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, text, mode="w"):
        with open(self.path, mode, encoding="utf-8") as fh:
            fh.write(text)

    def jumps(self, lt):
        return (lt.state.get("system") or {}).get("name")

    def test_shorter_rewrite_is_read_from_the_start(self):
        # an hour of events, then the game starts the file anew - shorter
        self.write(HEAD_A + "".join(line("17:%02d:00" % m, "Music", MusicTrack="x") for m in range(24, 59))
                   + line("17:59:00", "FSDJump", StarSystem="Alpha", SystemAddress=1, StarPos=[0, 0, 0]))
        lt = LiveTracker(self.tmp.name)
        lt.prime()
        self.assertEqual(self.jumps(lt), "Alpha")
        self.write(HEAD_B + line("18:40:43", "FSDJump", StarSystem="Beta", SystemAddress=2, StarPos=[1, 0, 0]))
        lt.poll_once()
        self.assertEqual(self.jumps(lt), "Beta")
        self.assertEqual(lt.rewrites, 1)

    def test_rewrite_already_longer_is_seen_by_its_header(self):
        self.write(HEAD_A + line("17:59:00", "FSDJump", StarSystem="Alpha", SystemAddress=1, StarPos=[0, 0, 0]))
        lt = LiveTracker(self.tmp.name)
        lt.prime()
        # the new file has grown past the old offset before the next poll
        self.write(HEAD_B + "".join(line("18:2%d:00" % m, "Music", MusicTrack="x") for m in range(10))
                   + line("18:40:43", "FSDJump", StarSystem="Gamma", SystemAddress=3, StarPos=[2, 0, 0]))
        lt.poll_once()
        self.assertEqual(self.jumps(lt), "Gamma")
        self.assertEqual(lt.rewrites, 1)

    def test_growing_file_is_no_rewrite(self):
        self.write(HEAD_A)
        lt = LiveTracker(self.tmp.name)
        lt.prime()
        self.write(line("17:30:00", "FSDJump", StarSystem="Delta", SystemAddress=4, StarPos=[3, 0, 0]), mode="a")
        lt.poll_once()
        self.assertEqual(self.jumps(lt), "Delta")
        self.assertEqual(lt.rewrites, 0)
        self.assertGreater(lt.last_poll, 0)


class ThreadWatchdogTest(unittest.TestCase):
    def test_restart_after_the_reader_stopped(self):
        with tempfile.TemporaryDirectory() as d:
            lt = LiveTracker(d, poll_s=0.05)
            lt.start()
            self.assertTrue(lt.alive())
            lt.stop()
            self.assertFalse(lt.alive())
            lt.restart()
            time.sleep(0.2)
            self.assertTrue(lt.alive())
            self.assertGreater(lt.last_poll, time.time() - 2)
            lt.stop()


if __name__ == "__main__":
    unittest.main()
