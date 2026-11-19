# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""5.0 CARRIER > JUMP PLAN: jump times learnt from your own jumps."""

import unittest

from fis import jumpplan


def _req(ts, dep, to):
    return {"event": "CarrierJumpRequest", "timestamp": ts, "DepartureTime": dep, "SystemName": to}


def _loc(ts, name):
    return {"event": "CarrierLocation", "timestamp": ts, "StarSystem": name}


JUMPS = [
    _req("2026-05-01T10:00:00Z", "2026-05-01T10:15:00Z", "Demo A"), _loc("2026-05-01T10:15:00Z", "Demo A"),
    _req("2026-05-01T10:21:00Z", "2026-05-01T10:37:00Z", "Demo B"), _loc("2026-05-01T10:37:00Z", "Demo B"),
    _req("2026-05-01T11:00:00Z", "2026-05-01T11:25:00Z", "Demo C"), _loc("2026-05-01T11:25:00Z", "Demo C"),
]


class TimingTest(unittest.TestCase):
    def test_learnt_from_own_jumps(self):
        tm = jumpplan.timing(JUMPS)
        c = tm["countdown"]
        self.assertTrue(c["learnt"])
        self.assertEqual(c["n"], 3)
        self.assertEqual(c["mid"], 16.0)            # 15, 16, 25 minutes
        self.assertEqual((c["lo"], c["hi"]), (15.2, 23.2))
        self.assertEqual(tm["cooldown"], 5.0)
        self.assertEqual(tm["fastest_next"], 6.0)   # arrived 10:15, next order 10:21
        self.assertEqual(tm["per_jump"], 21.0)

    def test_prior_without_jumps(self):
        tm = jumpplan.timing([])
        self.assertFalse(tm["countdown"]["learnt"])
        self.assertEqual(tm["countdown"]["mid"], 15.0)
        self.assertIsNone(tm["fastest_next"])

    def test_broken_times_are_skipped(self):
        evs = [_req("2026-05-01T10:00:00Z", None, "X"), _req("2026-05-01T10:00:00Z", "2026-05-01T09:00:00Z", "X")]
        self.assertEqual(jumpplan.timing(evs)["countdown"]["n"], 0)

    def test_trip_time_no_cooldown_after_the_last(self):
        tm = jumpplan.timing(JUMPS)
        tt = jumpplan.trip_time(3, tm)
        self.assertEqual(tt["mid"], 3 * 16 + 2 * 5)
        self.assertEqual(tt["lo"], round(3 * 15.2 + 10))
        self.assertEqual(tt["hi"], round(3 * 23.2 + 10))
        self.assertEqual(tt["n"], 3)
        self.assertIsNone(jumpplan.trip_time(0, tm))


if __name__ == "__main__":
    unittest.main()
