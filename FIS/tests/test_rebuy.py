# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""RB1 (5.1.0): the rebuy per ship in AIR WING, amber when the credits would
not pay it; the credits live from Status.json, else from the last login."""

import os
import unittest

from fis import shipview

VIEWS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "js", "views")


class _Arch:
    def __init__(self, evs):
        self.evs = evs

    def events(self):
        return list(self.evs)


class RebuyTest(unittest.TestCase):
    def test_credits_now(self):
        logins = _Arch([{"event": "LoadGame", "Credits": 5}, {"event": "Loadout"},
                        {"event": "LoadGame", "Credits": 9_000_000}])
        self.assertEqual(shipview.credits_now(logins, {}), 9_000_000)
        self.assertEqual(shipview.credits_now(logins, {"status": {"balance": 12_000_000}}), 12_000_000, "live first")
        self.assertIsNone(shipview.credits_now(_Arch([]), None))

    def test_air_wing_column(self):
        with open(os.path.join(VIEWS, "carrier.js"), encoding="utf-8") as fh:
            js = fh.read()
        self.assertIn('th("rebuy", t("Rebuy")', js)
        self.assertIn("rebuyCell(s.rebuy, data.credits)", js)
        self.assertIn("const short = credits !== null && credits !== undefined && credits < rebuy;", js)


if __name__ == "__main__":
    unittest.main()
