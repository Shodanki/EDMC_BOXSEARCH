# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""STATISTICS: latest Statistics event, ranks, growth over a period."""

import json
import os
import tempfile
import unittest

from fis import fleet as fl, stats
from fis.live import parse_ts


def _stat(ts, systems, ly, exo):
    return {"timestamp": ts, "event": "Statistics",
            "Exploration": {"Systems_Visited": systems, "Total_Hyperspace_Distance": ly,
                            "Total_Hyperspace_Jumps": systems, "Time_Played": 3600},
            "Exobiology": {"Organic_Data_Profits": exo}, "Squadron": {"Squadron_Bank_Credits_Deposited": 0}}


class StatsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        lines = [
            {"timestamp": "2026-01-01T10:00:00Z", "event": "Commander", "FID": "F1", "Name": "X"},
            _stat("2026-01-01T10:00:01Z", 100, 1000, 0),
            _stat("2026-01-20T10:00:01Z", 150, 2000, 5000000),
            {"timestamp": "2026-02-01T10:00:00Z", "event": "Rank", "Explore": 8, "Exobiologist": 5,
             "Combat": 2, "Trade": 13, "Empire": 4, "Federation": 0, "Soldier": 0, "CQC": 0},
            {"timestamp": "2026-02-01T10:00:00Z", "event": "Progress", "Explore": 27, "Exobiologist": 37},
            {"timestamp": "2026-02-01T10:00:00Z", "event": "Reputation", "Empire": 75.0, "Federation": 75.0},
            _stat("2026-02-01T10:00:01Z", 200, 2500, 7000000),
        ]
        with open(os.path.join(self.tmp.name, "Journal.2026-01-01T100000.01.log"), "w", encoding="utf-8") as fh:
            for e in lines:
                fh.write(json.dumps(e) + "\n")
        self.ar = fl.Archive(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_all_time(self):
        s = stats.build_statistics(self.ar)
        self.assertEqual(s["sections"]["Exploration"]["Systems_Visited"], 200)
        self.assertEqual(s["delta"]["Exploration"]["Systems_Visited"], 100)    # against the oldest
        self.assertNotIn("Squadron", s["sections"])
        self.assertEqual(s["derived"]["avg_jump"], 12.5)
        ranks = {r["key"]: r for r in s["ranks"]}
        self.assertEqual(ranks["Explore"]["name"], "Elite")
        self.assertEqual(ranks["Trade"]["name"], "Elite V")
        self.assertEqual(ranks["Exobiologist"]["name"], "Taxonomist")
        self.assertEqual(ranks["Explore"]["progress"], 27)
        self.assertEqual(ranks["Empire"]["name"], "Squire")
        self.assertEqual(s["ranks"][0]["key"], "Explore")                  # research first
        self.assertEqual(s["reputation"]["Empire"], 75.0)

    def test_period(self):
        now = parse_ts("2026-02-02T10:00:00Z")
        s = stats.build_statistics(self.ar, days=7, now=now)
        # 7 days back: the latest Statistics before 26.01. is the one of 20.01.
        self.assertEqual(s["since_ts"], parse_ts("2026-01-20T10:00:01Z"))
        self.assertEqual(s["delta"]["Exploration"]["Systems_Visited"], 50)
        self.assertEqual(s["delta"]["Exobiology"]["Organic_Data_Profits"], 2000000)

    def test_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(stats.build_statistics(fl.Archive(d))["empty"])


class OverTimeTest(unittest.TestCase):
    """ST1: series per day, first discoveries per month, surface map tiles."""

    def test_series_last_login_of_the_day(self):
        st = [_stat("2026-01-01T08:00:00Z", 100, 0, 0), _stat("2026-01-01T20:00:00Z", 110, 0, 0),
              _stat("2026-01-03T09:00:00Z", 130, 0, 7)]
        s = stats.series(st, None)
        day = parse_ts("2026-01-01T00:00:00Z")
        self.assertEqual(s["Exploration.Systems_Visited"], [[day, 110], [day + 2 * 86400, 130]])
        self.assertNotIn("Mining.Quantity_Mined", s)                   # not in the events
        self.assertEqual(stats.series(st, parse_ts("2026-01-02T00:00:00Z")), {})   # one day left: no line

    def test_first_discoveries_per_month(self):
        def scan(ts, body, disc, typ="Detailed"):
            return {"timestamp": ts, "event": "Scan", "SystemAddress": 1, "BodyID": body,
                    "ScanType": typ, "WasDiscovered": disc}
        evs = [scan("2026-07-01T10:00:00Z", 1, False), scan("2026-07-02T10:00:00Z", 1, False),   # the same body
               scan("2026-07-03T10:00:00Z", 2, True), scan("2026-08-01T10:00:00Z", 3, True),
               scan("2026-08-02T10:00:00Z", 4, False, "NavBeaconDetail")]
        self.assertEqual(stats.first_discoveries(evs), [
            {"month": "2026-07", "scanned": 2, "first": 1, "pct": 50.0},
            {"month": "2026-08", "scanned": 1, "first": 0, "pct": 0.0}])

    def test_dss_tiles(self):
        def saa(ts, addr, probes, target=6):
            return {"timestamp": ts, "event": "SAAScanComplete", "SystemAddress": addr,
                    "ProbesUsed": probes, "EfficiencyTarget": target}
        evs = [saa("2026-07-01T10:00:00Z", 1, 3), saa("2026-07-01T10:03:00Z", 1, 4),
               saa("2026-07-01T10:08:00Z", 1, 8), saa("2026-07-01T11:00:00Z", 1, 3),          # 52 min: no gap
               saa("2026-07-01T11:01:00Z", 2, 2)]                                               # another system
        d = stats.dss_tiles(evs)
        self.assertEqual((d["maps"], d["efficient"], d["efficient_pct"], d["probes_median"]), (5, 4, 80.0, 3))
        self.assertEqual((d["gap_n"], d["gap_median_s"]), (2, 300))
        self.assertIsNone(stats.dss_tiles([]))


class SessionsTest(unittest.TestCase):
    """RT1: systems and gathered value per hour, per session."""

    def test_sessions(self):
        from tests.test_unsold import _bodyvalue
        bv = _bodyvalue()

        def e(ts, ev, **kw):
            return dict({"timestamp": "2026-07-01T%sZ" % ts, "event": ev}, **kw)
        hmc = dict(PlanetClass="High metal content body", MassEM=1.0, TerraformState="", WasDiscovered=True,
                   WasMapped=True, ScanType="Detailed", SystemAddress=1)
        evs = [e("10:00:00", "LoadGame"), e("10:10:00", "FSDJump"), e("10:20:00", "FSDJump"),
               e("10:25:00", "Scan", BodyID=1, **hmc), e("10:26:00", "SAAScanComplete", SystemAddress=1, BodyID=1),
               e("10:40:00", "ScanOrganic", ScanType="Analyse", Species_Localised="Bacterium Aurasus"),
               e("11:00:00", "FSDJump"),
               e("13:00:00", "FSDJump"), e("13:05:00", "Scan", BodyID=1, **hmc)]      # after a pause; seen before
        out = stats.play_sessions(evs, bv, {"Bacterium Aurasus": {"value": 1000000}})
        self.assertEqual(len(out["sessions"]), 2)
        first = out["sessions"][1]
        mapped = bv.planet_value("High metal content body", "", 1.0, mapped=True)
        self.assertEqual((first["minutes"], first["jumps"], first["bodies"], first["bio"]), (60, 3, 1, 1000000))
        self.assertEqual(first["explo"], int(mapped))
        self.assertEqual((first["jumps_h"], first["value_h"]), (3.0, int(mapped + 1000000)))
        self.assertEqual((out["sessions"][0]["jumps"], out["sessions"][0]["bodies"]), (1, 0))
        self.assertEqual((out["n"], out["jumps_h"]), (1, 3.0))      # only the hour-long session counts
        self.assertFalse(stats.play_sessions(evs)["valued"])

    def test_whole_picture_fx0(self):
        """FX0 (user 18.11.2026): bodies others found count too, a body is mapped
        in a later session, and archive sessions with jumps but no scans (EDD
        keeps the jumps of 2020-22, hardly any scans) stay out of the value
        median instead of pulling it to 0 - measured 0.59 M -> 0 before."""
        from tests.test_unsold import _bodyvalue
        bv = _bodyvalue()

        def e(day, ts, ev, **kw):
            return dict({"timestamp": "2026-07-%02dT%sZ" % (day, ts), "event": ev}, **kw)
        hmc = dict(PlanetClass="High metal content body", MassEM=1.0, TerraformState="", WasDiscovered=True,
                   WasMapped=True, ScanType="Detailed", SystemAddress=1, BodyID=1)
        evs = [e(1, "10:00:00", "LoadGame"), e(1, "10:20:00", "Scan", **hmc), e(1, "10:40:00", "FSDJump"),
               e(2, "10:00:00", "LoadGame"), e(2, "10:20:00", "SAAScanComplete", SystemAddress=1, BodyID=1),
               e(2, "10:40:00", "FSDJump"),
               e(2, "11:00:00", "SAAScanComplete", SystemAddress=1, BodyID=1)]       # paid once only
        for d in (3, 4, 5):                       # archive: an hour of jumps, no scans kept
            evs += [e(d, "10:00:00", "LoadGame")] + [e(d, "%s:00" % h, "FSDJump") for h in ("10:20", "10:40", "11:00")]
        out = stats.play_sessions(evs, bv)
        scan = bv.planet_value("High metal content body", "", 1.0)
        full = bv.planet_value("High metal content body", "", 1.0, mapped=True)
        old = list(reversed(out["sessions"]))
        self.assertGreater(scan, 0)                                  # not a first discovery, still worth money
        self.assertEqual((old[0]["explo"], old[1]["explo"], old[1]["bodies"]), (int(scan), int(full - scan), 1))
        self.assertEqual([s["value_h"] for s in old[2:]], [None, None, None])
        self.assertEqual((out["n"], out["n_value"]), (5, 2))
        self.assertGreater(out["value_h"], 0)
        self.assertEqual(out["value_h"], (int(scan * 1.5) + int(full - scan)) / 2.0)


def _own_block(css, mark):
    """A theme block from its marker to the next "/* -- " section (5.1.0: later
    blocks may name standard - the ATLAS radar, user 24.11.)."""
    i = css.index(mark)
    j = css.find("\n/* -- ", i + len(mark))
    return css[i:j if j > 0 else len(css)]


class StatsLayoutTest(unittest.TestCase):
    """Test findings f-tip and st-bio (17.11.2026): long texts overlapped
    their neighbours in STATISTICS - checked by eye in headless Chrome at
    1600 x 900 in German, held here by the rules that fixed it."""

    WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")

    def _read(self, *parts):
        with open(os.path.join(self.WEB, *parts), encoding="utf-8") as fh:
            return fh.read()

    def test_tables_centre_numbers_and_their_headings(self):
        """TB1 (5.0.1, user 20.11.): in every table a column of numbers is
        centred with its heading, text columns stay left - one shared rule,
        last in the file so no table or theme block can undo it, and every
        table cell with a number carries the class num it keys on."""
        import glob
        import re
        css = self._read("css", "fis.css")
        rule = css[css.index("/* TB1 (5.0.1"):]
        for n in range(1, 17):
            self.assertIn("table:has(td.num:nth-child(%d)) :is(th, td):nth-child(%d)" % (n, n), rule)
        self.assertTrue(rule.rstrip().endswith("{ text-align: center; }"), "TB1 is the last rule")
        self.assertEqual(rule.count("{"), 1)
        # every view that builds a table marks its number cells
        for path in glob.glob(os.path.join(self.WEB, "js", "**", "*.js"), recursive=True):
            with open(path, encoding="utf-8") as fh:
                js = fh.read()
            if 'el("table"' not in js:
                continue
            self.assertRegex(js, r'el\("td", \{ class: "num', os.path.basename(path))
            for m in re.finditer(r'el\("td", \{ (class: "([^"]*)", )?text: (fmt|CR|cr)\(', js):
                self.assertIn("num", m.group(2) or "", "%s: a number cell without num" % os.path.basename(path))

    def test_briefing_values_stay_on_one_line(self):
        """BF1 (5.0.1): at 1600 px "112.0 ly" in NAVPOINTS and "5/6 · 83.3 %"
        in SPHERE broke over two lines; the bars keep one length."""
        css = self._read("css", "fis.css")
        self.assertIn(".hbar { display: grid; grid-template-columns: 11ch 1fr minmax(13ch, max-content);", css)
        self.assertIn("white-space: nowrap; }   /* BF1: \"5/6", css)
        self.assertIn(".navlist .nl-ly { text-align: right; color: var(--green); white-space: nowrap; }", css)
        self.assertEqual(css.count("3ch minmax(7ch, max-content) auto"), 2)          # base and station
        self.assertNotIn("3ch 7ch auto", css)

    def test_ship_bar_has_room(self):
        """KL1 (5.0.1): at 1600 px the tabs left the ship bar ~375 px and cut
        "SYS W…", "FUEL 1…", "TARGET D…"; below 2560 px it takes a row of its
        own in every theme, the tablet and phone rules come later and win."""
        import re
        css = self._read("css", "fis.css")
        kl1 = css[css.index("@media (max-width: 2559px) {"):]
        kl1 = kl1[:kl1.index("\n}\n")]
        self.assertIn("#top { grid-template-columns: auto 1fr; row-gap: 6px; }", kl1)
        self.assertIn(".shipbar { grid-column: 1 / -1; justify-content: space-between; }", kl1)
        self.assertIn(".sb-target .v, .sb-system .v { max-width: 40ch; }", kl1)
        self.assertLess(css.index("@media (max-width: 2559px)"), css.index("@media (max-width: 1100px) {\n  .tac-view"))
        # no theme sets its own header grid, so the row holds in all six
        for m in re.finditer(r':root\[data-theme="\w+"\] #top \{([^}]*)\}', css):
            self.assertNotIn("grid-template-columns", m.group(1))

    def test_bio_rates_and_learning_rows(self):
        js, css = self._read("js", "views", "statistics.js"), self._read("css", "fis.css")
        # BIO RATES: not the month row's fixed 64 px name column
        self.assertIn('class: "st-row st-month st-rate"', js)
        self.assertIn(".st-rate { grid-template-columns: minmax(0, 1.2fr)", css)
        self.assertGreater(css.index(".st-rate {"), css.index(".st-month {"))
        # LEARNING STATUS: the label keeps a minimum, the value wraps, the
        # reset row is a plain line with its button at the end
        self.assertIn(".st-learning .st-row { grid-template-columns: minmax(110px, 1fr)", css)
        self.assertIn(".st-learning .st-row > span { min-width: 0; overflow-wrap: anywhere; }", css)
        self.assertIn('class: "c-dim small st-row st-reset"', js)
        self.assertIn(".st-learning .st-reset { display: flex;", css)

    def test_no_scanlines_over_the_flat_themes(self):
        """User 18.11.2026: the lines over everything make Federation classic, Federation
        bridge and Belt industrial restless, above all the lettering - those three draw no
        scanlines and Belt's screens no line texture; standard, station and next keep them."""
        css = self._read("css", "fis.css")
        self.assertIn(':root[data-theme="console"] body.scanlines::after, :root[data-theme="bridge"] body.scanlines::after,\n'
                      ':root[data-theme="industrial"] body.scanlines::after { content: none; }', css)
        belt = css[css.index(':root[data-theme="industrial"] body:not(.obs) :is(.stat-view'):]
        belt = belt[:belt.index("}")]
        self.assertNotIn("repeating-linear-gradient(0deg", belt)
        self.assertIn('body.scanlines::after {', css)                   # the switch still works elsewhere
        self.assertIn(':root[data-theme="station"] body:not(.scanlines):not(.obs)::after', css)

    def test_nothing_blinks_for_ever(self):
        """User 18.11.2026: blinking is fine for an alarm, but not for as long as it lasts -
        no endless animation that blinks; alarms blink from their onset (blinkFor)."""
        import re
        css = self._read("css", "fis.css")
        endless = [m.group(0) for m in re.finditer(r"animation:[^;]*infinite", css)]
        self.assertEqual(endless, [])
        self.assertIn(".ann-master.warning.blinking { animation: annblink 1s steps(2) 8; }", css)
        self.assertIn(".sb-combat.alert.blinking .v { animation: annblink 1s steps(2) 8; }", css)
        self.assertIn('blinkFor("ship-master", data.master === "warning")', self._read("js", "views", "ship.js"))
        self.assertIn('blinkFor("combat-alert", level === "alert")', self._read("js", "app.js"))

    def test_remaining_pages_per_theme(self):
        """TH7 (user 18.11.2026): MINING, VEHICLE, PLANET, PLANET INFO, ATLAS and GALAXY take
        each theme's bars, chips and sub-tabs; Belt's bezel covers every page."""
        css = self._read("css", "fis.css")
        block = _own_block(css, "/* -- TH7 (18.11.): the remaining pages per theme")
        for theme in ("console", "bridge", "industrial", "station", "next"):
            self.assertIn(':root[data-theme="%s"] :is(.mine-view, .vehicle-view, .planet-view, .surface-view, .atlas-view, .galaxy-view) ' % theme, block)
        self.assertNotIn('data-theme="standard"', block)
        self.assertNotIn("animation", block)
        self.assertIn(".galaxy-view, .settings-view) .frame { padding: 5px;", css)

    def test_carrier_per_theme(self):
        """TH6 (user 18.11.2026): CARRIER per theme - the tritium tank through meter(), lines,
        services, last jumps and air wing; standard unchanged, nothing animated."""
        css, js = self._read("css", "fis.css"), self._read("js", "views", "carrier.js")
        self.assertIn('meter(pctTank, 100, pctTank < 25 ? "warn" : "")', js)
        block = _own_block(css, "/* -- TH6 (18.11.): CARRIER per theme")
        for theme in ("console", "bridge", "industrial", "station", "next"):
            self.assertIn(':root[data-theme="%s"] .carrier-view ' % theme, block)
        self.assertNotIn('data-theme="standard"', block)
        self.assertNotIn("animation", block)
        self.assertIn(":is(.stat-view, .ship-view, .tac-view, .briefing-view, .carrier-view, .mine-view, .vehicle-view, .planet-view, .surface-view, .atlas-view, .galaxy-view, .settings-view) .frame { padding: 5px;", css)

    def test_briefing_per_theme(self):
        """TH5 (user 18.11.2026): BRIEFING per theme - target block, sphere bars (hbar now
        hands its share to the theme as --p) and navpoints; standard unchanged, nothing animated."""
        css, ui = self._read("css", "fis.css"), self._read("js", "ui.js")
        self.assertIn('el("div", { class: "track", style: "--p: " + pct.toFixed(1) }', ui)
        block = _own_block(css, "/* -- TH5 (18.11.): BRIEFING per theme")
        for theme in ("console", "bridge", "industrial", "station", "next"):
            self.assertIn(':root[data-theme="%s"] .briefing-view .navlist li' % theme, block)
        self.assertNotIn('data-theme="standard"', block)
        self.assertNotIn("animation", block)
        self.assertIn(':root[data-theme="industrial"] :is(.stat-view, .ship-view, .tac-view, .briefing-view, .carrier-view, .mine-view, .vehicle-view, .planet-view, .surface-view, .atlas-view, .galaxy-view, .settings-view) .frame { padding: 5px;', css)

    def test_system_per_theme(self):
        """TH4 (user 18.11.2026): SYSTEM per theme - flight plan, report and head on the side;
        every rule bound to a non-standard theme, Belt's bezel on SYSTEM too."""
        css = self._read("css", "fis.css")
        block = _own_block(css, "/* -- TH4 (18.11.): SYSTEM per theme")
        for theme in ("console", "bridge", "industrial", "station", "next"):
            self.assertIn(':root[data-theme="%s"] .tac-view .leg' % theme, block)
        self.assertNotIn('data-theme="standard"', block)
        self.assertNotIn("animation", block)
        self.assertIn(':root[data-theme="industrial"] :is(.stat-view, .ship-view, .tac-view, .briefing-view, .carrier-view, .mine-view, .vehicle-view, .planet-view, .surface-view, .atlas-view, .galaxy-view, .settings-view) .frame { padding: 5px;', css)

    def test_ship_controls_on_the_left(self):
        """User 18.11.2026: the key bindings (CONTROLS, when switched on) sit in the left column
        under the hold, where there is room - not at the end of the long right column."""
        js = self._read("js", "views", "ship.js")
        self.assertIn('el("div", { class: "sh-col sh-left" }, cutaway(), logistics(), jumponium(), controlsFrame())', js)
        right = js[js.index('el("div", { class: "sh-col sh-right" }'):]
        self.assertNotIn("controlsFrame()", right[:right.index(chr(10))])

    def test_ship_status_is_one_compact_matrix(self):
        """User 18.11.2026: the SHIP status panel like a real annunciator - warnings, cautions and
        advisories in one compact matrix with aligned columns (no rows stretched over the width
        that wrap into a staircase), the ship and its key readings beside it."""
        css, js = self._read("css", "fis.css"), self._read("js", "views", "ship.js")
        self.assertIn(".ab-lamps { display: grid; grid-template-columns: repeat(6, 124px); gap: 4px; }", css)
        self.assertIn(".ann-band { display: grid; grid-template-columns: 82px max-content;", css)
        self.assertIn('el("div", { class: "ann-side" }, id, readings)', js)
        for label in ('t("Fuel")', 't("Cargo")', 't("Modules")'):
            self.assertIn(label, js[js.index("function annunciator"):js.index("function cutaway")])

    def test_ship_per_theme(self):
        """TH3 (user 18.11.2026): SHIP per theme. Hold, fuel, reservoir and the hull hand
        their share to meter(), module health carries --p; the hull meter is hidden in
        the standard look and drawn by every other theme; Belt's bezel covers SHIP too."""
        js, css = self._read("js", "views", "ship.js"), self._read("css", "fis.css")
        self.assertIn('meter(pct(s.hull) ?? 0, 100, "sh-hull-m " + hcls(s.hull))', js)
        self.assertIn("const bar = (v, max, cls) => meter(v || 0, max, cls);", js)
        self.assertIn('class: "m-h", style: "--p: " + (pct(m.health) ?? 0)', js)
        block = _own_block(css, "/* -- TH3 (18.11.): SHIP per theme.")
        self.assertIn(".sh-hull-m { display: none; }", block)
        for theme in ("console", "bridge", "industrial", "station", "next"):
            self.assertIn(':root[data-theme="%s"] .sh-ann .sh-hull-m { display: block;' % theme, block)
        self.assertNotIn('data-theme="standard"', block)
        self.assertIn(':root[data-theme="industrial"] :is(.stat-view, .ship-view, .tac-view, .briefing-view, .carrier-view, .mine-view, .vehicle-view, .planet-view, .surface-view, .atlas-view, .galaxy-view, .settings-view) .frame { padding: 5px;', css)

    def test_theme_lists_agree_and_bridge_is_complete(self):
        """TH2 (user 18.11.2026): the old console look stays as "Federation classic",
        "Federation bridge" is a new theme. Boot script and picker list the same
        themes; the new one defines every palette token the other themes override."""
        import re
        boot, app, css, i18n = (self._read("js", "theme-boot.js"), self._read("js", "app.js"),
                                self._read("css", "fis.css"), self._read("js", "i18n.js"))
        boot_list = re.findall(r'"([a-z]+)"', boot[boot.index("var THEMES = ["):boot.index("];", boot.index("var THEMES = ["))])
        app_block = app[app.index("const THEMES = ["):app.index("]];", app.index("const THEMES = ["))]
        self.assertEqual(boot_list, re.findall(r'\["([a-z]+)", N_', app_block))
        self.assertIn("bridge", boot_list)
        for label in ("Theme: Federation classic", "Theme: Federation bridge"):
            self.assertIn('N_("' + label + '")', app)
            self.assertIn('"' + label + '": "', i18n)
        # the palette every theme overrides (derived tokens such as --line follow from it)
        std = css[css.index(':root[data-theme="industrial"] {'):css.index("}", css.index(':root[data-theme="industrial"] {'))]
        bridge = css[css.index(':root[data-theme="bridge"] {'):css.index("}", css.index(':root[data-theme="bridge"] {'))]
        for token in re.findall(r"(--[a-z0-9-]+):", std):
            self.assertIn(token + ":", bridge, token)

    def test_themes_draw_statistics_their_own_way(self):
        """TH1 (user 18.11.2026): each theme its own STATISTICS - console rings and
        pills, industrial segments, station dots and prompt titles without a blinking
        cursor, next flat with a lead figure. The standard theme stays as it was:
        every new rule is bound to a theme other than standard."""
        import re
        css, js = self._read("css", "fis.css"), self._read("js", "views", "statistics.js")
        block = css[css.index("/* 5.0 TH1: each theme's own STATISTICS"):css.index("/* -- Federation bridge (TH2")]
        rules = [r for r in re.findall(r"^(:root[^{]*)\{", block, re.M)]
        self.assertTrue(rules)
        for r in rules:
            self.assertRegex(r, r':root\[data-theme="(console|bridge|industrial|station|next)"\] (body:not\(\.obs\) )?(\.stat-view |:is\(\.stat-view[^)]*\) )')
        self.assertNotIn('data-theme="standard"', block)
        for theme, mark in (("console", "conic-gradient(var(--cyan) calc(var(--p, 0) * 1%)"),
                            ("industrial", "repeating-linear-gradient(90deg, var(--scr-c) 0 6px"),          # TH1b: teal screen, amber cap
                            ("industrial", "box-shadow: 2px 0 0 var(--amber)"),
                            ("station", 'content: "> "'), ("next", ".st-lead > .num:not(.small) { font: 600 26px")):
            self.assertIn(mark, block, theme)
        # no blinking cursor in any statistics theme (user 18.11.: it irritates)
        self.assertNotIn("animation", block.split("@media (prefers-reduced-motion")[0])
        self.assertNotIn('content: "_"', block)
        # the views hand the share to the theme through meter(); the lead figure is marked
        self.assertEqual(js.count("meter("), 4)                  # 5.1.0: + regions visited (RECORDS & ATLAS)
        self.assertIn('rows.length ? "st-row" : "st-row st-lead"', js)

    def test_sub_tabs_hold_every_frame_once(self):
        """Night run 18.11.2026: STATISTICS in sub-tabs of fixed columns -
        every frame in exactly one pane, nothing dropped, labels translated."""
        import re
        js, css, i18n = self._read("js", "views", "statistics.js"), self._read("css", "fis.css"), self._read("js", "i18n.js")
        block = js[js.index("const PANES = ["):js.index("];", js.index("const PANES = ["))]
        keys = re.findall(r'"([A-Za-z]+)"', re.sub(r'N_\("[^"]*"\)', "", block))
        panes = ["overview", "trends", "rates", "learning", "atlas"]
        frames = list(keys)
        for k in panes:                     # each pane id once; "learning" is a pane and its frame
            frames.remove(k)
        cards = re.findall(r'^  \["([A-Z]+)", N_\(', js, re.M)
        expected = ["ranks", "overTime", "firstFinds", "surfaceMaps", "bioRates", "perSession", "timePerSystem", "learning",
                    "carrierMoney"] + cards          # CT2: the carrier's money in OVERVIEW
        expected += ["records", "regions", "starsWorlds", "journey", "travel", "ships", "bioCatalogue"]   # 5.1.0 ST2-ST9
        self.assertEqual(sorted(frames), sorted(expected))          # each once, none missing
        for k in expected[:9]:
            self.assertIn(k + ": () => " + k + "()", js)
        for label in ("OVERVIEW", "HISTORY", "RATES & TIMES", "LEARNING STATUS", "Nothing here yet."):
            self.assertIn('N_("' + label + '")' if label != "Nothing here yet." else 't("' + label + '")', js)
            self.assertIn('"' + label + '": "', i18n)
        # a custom property cannot go through style.foo = ...; it is set as text
        self.assertIn('style: "--n: " + built.length', js)
        self.assertIn(".st-cols { display: grid; grid-template-columns: repeat(var(--n, 3), minmax(0, 1fr));", css)
        self.assertIn("align-items: start; }", css[css.index(".st-cols {"):])
        # LEDGER and TRADE still use the old grid
        self.assertIn(".stat-grid { display: grid;", css)


if __name__ == "__main__":
    unittest.main()
