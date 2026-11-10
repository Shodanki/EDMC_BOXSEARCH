# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""M8: combat mode from Status.json flags and journal events."""

import unittest

from fis import combat
from fis.live import LiveTracker
from fis.model import build_ship

HP = 1 << combat.HARDPOINTS
NOW = 1_800_000_000.0


def _live(flags=0, hits=None):
    return {"status": {"flags": flags}, "combat_hits": hits or {}}


class TestCombat(unittest.TestCase):
    def test_quiet(self):
        self.assertEqual(combat.combat_state(_live(), NOW), {"level": None, "reasons": [], "until": None})

    def test_ready_with_hardpoints(self):
        c = combat.combat_state(_live(HP, {"target": NOW - 10}), NOW)
        self.assertEqual((c["level"], c["reasons"], c["until"]), ("ready", ["hardpoints", "target"], NOW + 50))
        # a lock long ago is just hardpoints
        self.assertEqual(combat.combat_state(_live(HP, {"target": NOW - 100}), NOW)["reasons"], ["hardpoints"])

    def test_alert_and_decay(self):
        c = combat.combat_state(_live(0, {"attacked": NOW - 5, "shields_down": NOW - 20}), NOW)
        self.assertEqual((c["level"], c["reasons"], c["until"]), ("alert", ["attacked", "shields_down"], NOW + 25))
        self.assertIsNone(combat.combat_state(_live(0, {"attacked": NOW - 31}), NOW)["level"])
        self.assertEqual(combat.combat_state(_live(1 << combat.INTERDICTED), NOW)["level"], "alert")

    def test_docked_is_never_combat(self):
        flags = HP | 1 << combat.DOCKED | 1 << combat.DANGER
        self.assertIsNone(combat.combat_state(_live(flags, {"attacked": NOW - 1}), NOW)["level"])

    def test_events_through_the_live_tracker(self):
        lt = LiveTracker(".")
        lt._replaying = True              # no hub needed
        for e in ({"event": "UnderAttack", "Target": "Fighter", "timestamp": "2027-01-15T08:00:00Z"},
                  {"event": "HullDamage", "Health": 0.9, "PlayerPilot": True, "Fighter": False,
                   "timestamp": "2027-01-15T08:00:01Z"},
                  {"event": "ShipTargeted", "TargetLocked": True, "Ship": "anaconda",
                   "timestamp": "2027-01-15T08:00:02Z"}):
            lt.feed(e)
        hits = lt.snapshot()["combat_hits"]
        self.assertEqual(sorted(hits), ["hull_hit", "target"])       # the fighter's attack is not yours
        lt.feed({"event": "Docked", "StationName": "Test Port", "timestamp": "2027-01-15T08:05:00Z"})
        self.assertEqual(lt.snapshot()["combat_hits"], {})

    def test_build_ship_carries_it(self):
        self.assertEqual(build_ship(_live(HP))["combat"]["level"], "ready")


if __name__ == "__main__":
    unittest.main()
