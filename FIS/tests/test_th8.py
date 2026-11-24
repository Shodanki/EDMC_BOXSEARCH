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

    def _scoped_and_still(self, block, standard=False):
        """Every rule of a TH8 block is scoped to a non-standard theme (or only
        hides / shows a theme element), and nothing moves. ``standard``: the
        user asked for this one in standard too (ATLAS radar, 24.11.)."""
        rules = re.sub(r"/\*.*?\*/", "", block, flags=re.S)
        self.assertNotIn("animation", rules)
        self.assertNotIn("@keyframes", rules)
        self.assertNotIn("blink", rules)
        for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", rules):
            sel = sel.strip()
            themed = ('[data-theme="' in sel and sel.startswith(":root")
                      and (standard or 'data-theme="standard"' not in sel))
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

    def test_vehicle_tank_meter_and_switches(self):
        js = _read("js", "views", "vehicle.js")
        self.assertIn('meter(pct, 100, "vh-fuel"', js)
        self.assertNotIn('"bar vh-fuel', js)
        self.assertIn('el("div", { class: "vh-switches" }, ...switches)', js)
        # standard: the meter drawn as the old bar (green / amber / red, glow)
        self.assertIn(".vh-fuel.lbar i { background: var(--green); box-shadow: 0 0 6px rgba(var(--green-rgb), .5); }", self.css)
        block = _block(self.css, "/* -- TH8 (5.1.0) VEHICLE")
        self._scoped_and_still(block)
        self.assertIn(':root[data-theme="console"] .vehicle-view .vh-switches .chip', block)       # capsules
        self.assertIn(':root[data-theme="industrial"] .vehicle-view .vh-switches .chip::before', block)  # plaques

    def test_next_has_its_own_colours(self):
        """PLANET map (and every canvas) takes its colours through ui.C; "next"
        had none of its own but the accent - now a full token set, the accent
        (--cyan) still the browser's."""
        i = self.css.index(':root[data-theme="next"] {')
        block = self.css[i:self.css.index("}", i)]
        for tok in ("--bg:", "--text:", "--dim:", "--green:", "--amber:", "--red:", "--violet:", "--panel:", "--ink:",
                    "--green-rgb:", "--dim-rgb:", "--white-rgb:"):
            self.assertIn(tok, block)
        self.assertNotIn("--cyan:", block)
        self.assertIn('root.style.setProperty("--cyan", accent', _read("js", "theme-boot.js"))
        self.assertIn("const COL = { ship: C.cyan", _read("js", "views", "surface.js"))

    def test_planet_info_short_frames_and_station_sheet(self):
        js = _read("js", "views", "planet.js")
        for name in ("RINGS", "COLLECTED HERE", "SIGNALS", "STAR"):
            self.assertIn('left.push(frame(t("%s")' % name, js)
        block = _block(self.css, "/* -- TH8 (5.1.0) PLANET INFO")
        self._scoped_and_still(block)
        self.assertIn(':root[data-theme="station"] .planet-view .tile { display: flex;', block)
        self.assertIn("dotted", block)

    def test_galaxy_canvas_in_theme_colours(self):
        """GALAXY drew closed / open boxels and the flight path in standard's
        fixed green, amber and violet-to-teal; now from the theme tokens."""
        js = _read("js", "views", "galaxy.js")
        self.assertIsNone(re.search(r"rgba\(\d{2,3},\d{2,3},\d{2,3}", js), "a fixed colour left in the canvas")
        self.assertIsNone(re.search(r"rgba\(\$\{Math\.round\(", js))
        self.assertIn('alpha("green", (.08 + .32 * gF)', js)
        self.assertIn('mixRGBA("violet", "cyan", k', js)

    def test_settings_switches_and_fields(self):
        block = _block(self.css, "/* -- TH8 (5.1.0) SETTINGS")
        self._scoped_and_still(block)
        self.assertNotIn("transition", block)                 # the knob jumps, nothing slides
        for theme in ("console", "bridge", "station", "next"):
            self.assertIn(':root[data-theme="%s"] .settings-view .st-set input[type="checkbox"]:checked' % theme, block)
        self.assertIn("border-bottom: 2px solid var(--cyan)", block)       # next: underlined fields

    def test_atlas_radar_in_station(self):
        js = _read("js", "views", "atlas.js")
        self.assertIn("g.shadowBlur = 0;", js)                       # the glow ends with the hits
        self.assertNotIn("requestAnimationFrame", js)                # a still radar, no sweep
        block = _block(self.css, "/* -- TH8 (5.1.0) ATLAS")
        self._scoped_and_still(block, standard=True)
        self.assertIn(':root:is([data-theme="station"], [data-theme="standard"]) .atlas-view .at-side { order: -1; }', block)

    def test_atlas_map_style_per_theme(self):
        """User 24.11.: the station radar also in standard, something of their
        own for the other themes, next as it was."""
        js = _read("js", "views", "atlas.js")
        self.assertIn('const MAP_STYLE = { standard: "radar", station: "radar", console: "scope", industrial: "survey", '
                      'bridge: "tactical" };', js)
        self.assertIn('MAP_STYLE[document.documentElement.dataset.theme] || "plain"', js)     # next: plain
        for f in ("function bezel(", "function surveyGrid(", "function mapHit(", "function mapGrid("):
            self.assertIn(f, js)

    def test_galaxy_next_hop_can_be_switched_off(self):
        """User 24.11.: NEXT HOP in GALAXY on and off - one more entry under
        LAYERS (on by default, kept per browser), re-drawing the side column."""
        js = _read("js", "views", "galaxy.js")
        self.assertIn('["nexthop", N_("next hop")]', js)
        self.assertIn("if (hop && on.nexthop) side.append(hopFrame());", js)
        self.assertIn('if (k === "nexthop") renderSide();', js)
        self.assertIn("for (const [k] of LAYERS) if (on[k] === undefined) on[k] = true;", js)

    def test_galaxy_carrier_label_off_the_dashed_line(self):
        """5.1.0: the carrier's label lay on its dashed path / jump line - it
        now takes the side no line leaves on, with a dark rim."""
        js = _read("js", "views", "galaxy.js")
        self.assertIn("function labelAway(g, text, x, y, lines, gap)", js)
        self.assertIn("function pathNeighbours(pts, x, y)", js)
        self.assertIn("labelAway(g, main, sx, sy, away.concat(jumpV ? [jumpV] : []), 13);", js)
        self.assertIn("labelAway(g, jump, jx, jy, [[sx - jx, sy - jy]], 10);", js)
        self.assertNotIn("g.fillText(main, sx + 13, sy + 4)", js)


if __name__ == "__main__":
    unittest.main()
