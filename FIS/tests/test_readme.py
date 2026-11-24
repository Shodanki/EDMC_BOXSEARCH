# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""The main README's top (user 20.11.2026): a SYSTEM teaser image after the
intro and "What you get" right before Operation - the image only on GitHub,
never in the download (FIS/docs is export-ignore)."""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


class ReadmeTop(unittest.TestCase):
    def setUp(self):
        self.md = _read("README.md")

    def test_teaser_after_the_intro_not_shipped(self):
        m = re.search(r"!\[[^\]]*\]\((FIS/docs/screenshots/demo_system\.png)\)\n\*[^*]+\(demo data\)\.\*", self.md)
        self.assertIsNotNone(m, "image with a one-line caption")
        self.assertLess(self.md.index("Systematic, exhaustive sphere survey"), m.start())
        self.assertLess(m.start(), self.md.index("**SHBOX FIS** (since 4.4)"))
        self.assertTrue(os.path.isfile(os.path.join(ROOT, *m.group(1).split("/"))))
        self.assertIn("FIS/docs export-ignore", _read(".gitattributes"))
        self.assertNotIn("demo_system.png", _read("SHBOXSEARCH.manifest"))

    def test_what_you_get_right_before_operation(self):
        wyg = self.md.index("\n## What you get\n")
        op = self.md.index("\n# Operation\n")
        self.assertLess(wyg, op)
        between = self.md[wyg:op]
        self.assertNotIn("\n# ", between)
        self.assertEqual(between.count("\n## "), 1)
        self.assertIn("[What you get](#what-you-get)", self.md[:wyg])
        # every FIS page it names is a page of the FIS
        nav = (_read("FIS", "web", "index.html") + _read("FIS", "web", "js", "app.js")).lower()
        for page in ("BRIEFING", "SYSTEM", "GALAXY", "PLANET INFO", "ATLAS", "SHIP", "VEHICLE",
                     "CARRIER", "STATISTICS", "LEDGER", "TRADE"):
            self.assertIn(page, between)
            self.assertIn(page.lower(), nav, page)


if __name__ == "__main__":
    unittest.main()
