# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""MP3 (5.1.0): mining fields rated - purity, prospectors per good rock, by-catch."""

import os
import unittest

from fis import fieldrating as fr


def field(ring, day, shares, prospectors, refined):
    """A session in one ring: rocks with these tritium shares, prospectors, tonnes refined."""
    t0 = "2026-11-%02dT10:" % day
    evs = [{"event": "SupercruiseExit", "timestamp": t0 + "00:00Z", "Body": ring, "BodyType": "PlanetaryRing"}]
    n = 0
    for i in range(prospectors):
        n += 1
        evs.append({"event": "LaunchDrone", "timestamp": t0 + "%02d:%02dZ" % (n // 60 + 1, n % 60), "Type": "Prospector"})
    for i, s in enumerate(shares):
        n += 1
        mats = [{"Name": "Tritium", "Proportion": s}] if s else [{"Name": "Bromellite", "Proportion": 10.0}]
        evs.append({"event": "ProspectedAsteroid", "timestamp": t0 + "%02d:%02dZ" % (n // 60 + 1, n % 60),
                    "Materials": mats, "Content": "$AsteroidMaterialContent_Medium;"})
    for name, t in refined:
        for _i in range(t):
            n += 1
            evs.append({"event": "MiningRefined", "timestamp": t0 + "%02d:%02dZ" % (n // 60 + 1, n % 60),
                        "Type": "$%s_name;" % name.lower(), "Type_Localised": name})
    evs.append({"event": "Docked", "timestamp": "2026-11-%02dT11:59:00Z" % day})
    return evs


class FieldRatingTest(unittest.TestCase):
    def test_rated_against_the_own_average(self):
        evs = (field("Rich Ring", 1, [30, 25, 20, 0], 4, [("Tritium", 30), ("Bromellite", 10)])
               + field("Poor Ring", 2, [10, 8, 0, 0, 0, 12, 20], 14, [("Tritium", 20)]))
        rows = {r["ring"]: r for r in fr.rate_fields(evs)}
        rich, poor = rows["Rich Ring"], rows["Poor Ring"]
        # typical tritium share: median of 30, 25, 20, 10, 8, 12, 20 = 20 %
        self.assertEqual(rich["good_pct"], 20.0)
        self.assertEqual((rich["purity"], rich["good"], rich["per_good"]), (75, 3, 1.3))
        self.assertEqual((rich["bycatch_t"], rich["bycatch_pct"], rich["bycatch"][0]["name"]), (10, 25, "Bromellite"))
        self.assertEqual((poor["purity"], poor["good"], poor["per_good"]), (57, 1, 14.0))
        self.assertEqual((rich["rating"], poor["rating"]), ("good", "poor"))
        self.assertEqual(fr.rate_fields(evs)[0]["ring"], "Rich Ring", "the best first")

    def test_one_field_of_a_material_is_fair(self):
        rows = fr.rate_fields(field("Only Ring", 3, [20, 20], 2, [("Tritium", 5)]))
        self.assertEqual(rows[0]["rating"], "fair")

    def test_shown_under_history(self):
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "js", "views",
                               "mining.js"), encoding="utf-8") as fh:
            js = fh.read()
        self.assertIn('el("div", { class: "mine-col" }, fields(), methods(), goods())', js)


if __name__ == "__main__":
    unittest.main()
