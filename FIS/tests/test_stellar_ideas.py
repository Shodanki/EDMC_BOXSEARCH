# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""5.1.0, ideas seen in StellarCartography (MIT, ideas only, no code):
SC1 source and age in SYSTEM and PLANET INFO, SC2 legend entries that
switch their GALAXY layer, SC3 the codex regions' outlines in GALAXY."""

import os
import unittest

from fis import regions

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")


def _read(*parts):
    with open(os.path.join(WEB, *parts), encoding="utf-8") as fh:
        return fh.read()


class RegionsTest(unittest.TestCase):
    def test_outlines_run_length_coded(self):
        # two regions split at x = 0, none beyond z 50000
        def find(x, y, z):
            if z > 50000:
                return None
            return (1, "Inner") if x < 0 else (2, "Outer")
        r = regions.build(find, ["Inner", "Outer"])
        self.assertEqual((r["w"], r["h"], r["step"]), (361, 401, 250))
        row0 = r["rows"][0]
        self.assertEqual(row0, [1, 180, 2, 181], "x -45000..-250 inner, 0..45000 outer")
        self.assertEqual(r["rows"][-1], [0, 361], "beyond z 50000: no region")
        self.assertEqual(r["names"], {"1": "Inner", "2": "Outer"})
        self.assertEqual([lab[0] for lab in r["labels"]], [1, 2])
        self.assertLess(r["labels"][0][1], 0)
        self.assertGreater(r["labels"][1][1], 0)

    def test_drawn_as_a_layer(self):
        js = _read("js", "views", "galaxy.js")
        self.assertIn('["regions", N_("regions")]', js)
        self.assertIn("if (on.regions) drawRegions(W, H);", js)
        self.assertIn('getJSON("/api/regions")', js)


class LegendTest(unittest.TestCase):
    def test_legend_entries_switch_their_layer(self):
        js = _read("js", "views", "galaxy.js")
        self.assertIn('legendChip("systems", "c-green", "■ " + t("visited"))', js)
        self.assertIn('legendChip("carrier", "c-amber"', js)
        self.assertIn("onclick: () => setLayer(k, !on[k])", js)
        self.assertIn(".legend .lg-chip.off { opacity: .35;", _read("css", "fis.css"))


class SourceAgeTest(unittest.TestCase):
    def test_shown_with_their_age(self):
        self.assertIn("export function ageText(tr, ts)", _read("js", "ui.js"))
        tac = _read("js", "views", "tactical.js")
        self.assertIn('t("updated {a}", { a: ageText(t, sys.known_updated) })', tac)
        self.assertIn('t("your scans: journal, {a}", { a: ageText(t, sys.scanned_ts) })', tac)
        self.assertIn('t("your scan (journal), {a}", { a: ageText(t, pv.scan_ts) })', _read("js", "views", "planet.js"))
        with open(os.path.join(os.path.dirname(WEB), "fis", "model.py"), encoding="utf-8") as fh:
            m = fh.read()
        self.assertIn('"known_updated": srow["updated"] if srow is not None else None', m)
        self.assertIn('"provenance": {"scan_ts": r["scan_ts"], "updated": r["updated"],', m)


if __name__ == "__main__":
    unittest.main()
