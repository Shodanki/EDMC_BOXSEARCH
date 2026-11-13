# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""4.11: a damaged StarPos in a journal line is no position - GALAXY, the
live state and the carriers skip it instead of failing (the plugin does the
same since 4.9.1, procgen.star_pos)."""

import unittest

from fis import galaxy
from fis.live import LiveTracker, star_pos

BAD = ["garbage", [1.0, 2.0], [1.0, "x", 3.0], [float("nan"), 0.0, 0.0], [True, 0.0, 0.0],
       [1.0, 2.0, 3.0, 4.0], None, {"x": 1}]


def jump(ts, name, addr, pos):
    return {"timestamp": "2026-11-13T10:%02d:00Z" % ts, "event": "FSDJump", "StarSystem": name,
            "SystemAddress": addr, "StarPos": pos, "JumpDist": 10.0}


class Archive:
    def __init__(self, evs):
        self.evs = evs

    def events(self):
        return self.evs


class TestStarPos(unittest.TestCase):
    def test_rule(self):
        self.assertEqual(star_pos([1, 2.5, "-3"]), [1.0, 2.5, -3.0])
        self.assertEqual(star_pos((0, 0, 0)), [0.0, 0.0, 0.0])
        for v in BAD:
            self.assertIsNone(star_pos(v), repr(v))

    def test_galaxy_skips_damaged_positions(self):
        evs = [jump(i, "Bad %d" % i, 100 + i, v) for i, v in enumerate(BAD)]
        evs.append(jump(30, "Good", 7, [10.0, -5.0, 20.0]))
        path = galaxy.flight_path(Archive(evs))
        self.assertEqual([p["name"] for p in path], ["Good"])
        self.assertEqual((path[0]["x"], path[0]["z"]), (10.0, 20.0))

    def test_live_state_keeps_no_damaged_position(self):
        lt = LiveTracker(journal_dir=".")
        lt.feed(jump(1, "Bad", 5, "garbage"))
        self.assertIsNone(lt.state["system"]["pos"])
        lt.feed(jump(2, "Good", 6, [1.0, 2.0, 3.0]))
        self.assertEqual(lt.state["system"]["pos"], [1.0, 2.0, 3.0])


if __name__ == "__main__":
    unittest.main()
