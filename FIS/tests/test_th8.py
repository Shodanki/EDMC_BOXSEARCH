# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
TH8 (5.1.0): the remaining pages per theme, as proposed on 18.11. and built
on 24.11. Every rule goes through the shared building blocks, is scoped to a
non-standard theme (standard stays as it was), and moves nothing: no
animation, no blinking, no scanlines in classic, bridge and Belt.
"""
import os
import re
import unittest

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")


def _read(*parts):
    with open(os.path.join(WEB, *parts), encoding="utf-8") as fh:
        return fh.read()


def _block(css, start):
    """The CSS from a marker comment to the next TH8 / section comment."""
    i = css.index(start)
    j = css.find("\n/* ", i + len(start))
    return css[i:j if j > 0 else len(css)]


class TH8Test(unittest.TestCase):
    css = _read("css", "fis.css")

    def _scoped_and_still(self, block):
        """Every rule of a TH8 block is scoped to a non-standard theme (or only
        hides / shows a theme element), and nothing moves."""
        rules = re.sub(r"/\*.*?\*/", "", block, flags=re.S)
        self.assertNotIn("animation", rules)
        self.assertNotIn("@keyframes", rules)
        self.assertNotIn("blink", rules)
        for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", rules):
            sel = sel.strip()
            themed = ':root[data-theme="' in sel and 'data-theme="standard"' not in sel
            neutral = body.strip() in ("display: none;", "font-weight: inherit;")    # keeps standard as it was
            self.assertTrue(themed or neutral, "unscoped TH8 rule: " + sel)

    def test_mining_sub_tabs_and_accents(self):
        js = _read("js", "views", "mining.js")
        for k in ('tb("live", t("LIVE"))', 'tb("history", t("HISTORY"))', 'tb("places", t("PLACES"))'):
            self.assertIn(k, js)
        self.assertIn('localStorage.setItem("fis.mine.tab", k)', js)
        block = _block(self.css, "/* -- TH8 (5.1.0) MINING")
        self._scoped_and_still(block)
        self.assertIn(':root[data-theme="industrial"] .mine-view .mh-count b', block)      # Belt: counter
        self.assertIn(':root[data-theme="station"] .mine-view .mine-rate-big { display: block;', block)
        self.assertIn(".mine-rate-big { display: none; }", block)                          # standard unchanged
        self.assertIn(':root[data-theme="bridge"] .mine-view .mine-list .cg:nth-child(even)', block)


if __name__ == "__main__":
    unittest.main()
