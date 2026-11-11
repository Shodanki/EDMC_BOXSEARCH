# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""What the rocks of a ring held, and what to expect at a kind of hotspot."""

import unittest

from fis import prospect


def _rock(mats, ml=None):
    e = {"event": "ProspectedAsteroid", "timestamp": "2026-11-10T10:00:00Z",
         "Materials": [{"Name": k, "Name_Localised": k.capitalize(), "Proportion": p} for k, p in mats]}
    if ml:
        e["MotherlodeMaterial"] = ml
    return e


def _exit(ring):
    return {"event": "SupercruiseExit", "Body": ring, "BodyType": "PlanetaryRing"}


EVENTS = [
    _exit("Alpha 1 A Ring"),
    _rock([("tritium", 20.0), ("bromellite", 10.0)]),
    _rock([("tritium", 10.0)], ml="Bromellite"),
    {"event": "SupercruiseEntry"},
    _rock([("gold", 30.0)]),                     # in supercruise: no ring, not counted
    _exit("Beta 2 B Ring"),
    _rock([("tritium", 12.0), ("liquidoxygen", 8.0)]),
    {"event": "FSDJump"},
    {"event": "SupercruiseExit", "Body": "Gamma 3", "BodyType": "Planet"},
    _rock([("painite", 25.0)]),                  # not at a ring
]


class TestProspect(unittest.TestCase):
    def test_rocks_per_ring(self):
        p = prospect.ring_prospects(EVENTS)
        self.assertEqual(sorted(p), ["Alpha 1 A Ring", "Beta 2 B Ring"])
        s = prospect.summary(p["Alpha 1 A Ring"])
        self.assertEqual(s["rocks"], 2)
        self.assertEqual([(m["key"], m["share"], m["avg"]) for m in s["mats"]],
                         [("tritium", 100, 15.0), ("bromellite", 50, 10.0)])
        self.assertEqual(s["motherlodes"], [("Bromellite", 1)])

    def test_expectations_by_ring_class_and_hotspot(self):
        p = prospect.ring_prospects(EVENTS)
        hs = {"Alpha 1 A Ring": ("Icy", ["tritium"]), "Beta 2 B Ring": ("Icy", ["tritium"])}
        pool = prospect.expectations(p, hs)
        e = prospect.expected_for(pool, "Icy", "tritium", skip_ring="Alpha 1 A Ring")
        self.assertEqual((e["rings"], e["rocks"]), (2, 3))
        self.assertIn("liquidoxygen", [m["key"] for m in e["mats"]])
        # only this ring has the data: nothing "expected" beyond it
        only = prospect.expectations(p, {"Alpha 1 A Ring": ("Icy", ["tritium"])})
        self.assertIsNone(prospect.expected_for(only, "Icy", "tritium", skip_ring="Alpha 1 A Ring"))
        self.assertEqual(prospect.ring_class("eRingClass_MetalRich"), "MetalRich")

    def test_l1_range_narrows_with_data(self):
        lo, hi = prospect.wilson(3, 4)
        self.assertTrue(lo < 40 and hi > 90, (lo, hi))
        lo2, hi2 = prospect.wilson(300, 400)
        self.assertTrue(hi2 - lo2 < 10 and lo2 <= 75 <= hi2, (lo2, hi2))
        s = prospect.summary(prospect.ring_prospects(EVENTS)["Alpha 1 A Ring"])
        self.assertTrue(s["thin"] and s["mats"][0]["lo"] < 100 == s["mats"][0]["hi"])

    def test_l2_thin_group_leans_on_the_class(self):
        evs = [_exit("Big 1 A Ring")] + [_rock([("tritium", 10.0)]) for _ in range(60)]
        evs += [_exit("Small 2 A Ring"), _rock([("tritium", 10.0), ("gold", 5.0)]),
                _rock([("gold", 5.0)])]
        p = prospect.ring_prospects(evs)
        hs = {"Big 1 A Ring": ("Icy", ["tritium"]), "Small 2 A Ring": ("Icy", ["painite"])}
        pool = prospect.expectations(p, hs)
        e = prospect.expected_for(pool, "Icy", "painite", skip_ring="Other")
        self.assertEqual((e["level"], e["borrowed"]), ("class", 62))
        gold = next(m for m in e["mats"] if m["key"] == "gold")
        # 2 of 2 rocks alone would be 100 %; leaning on the class pulls it down
        self.assertLess(gold["share"], 40)
        big = prospect.expected_for(pool, "Icy", "tritium", skip_ring="Other")
        self.assertEqual(big["level"], "hotspot")             # enough rocks of its own


if __name__ == "__main__":
    unittest.main()
