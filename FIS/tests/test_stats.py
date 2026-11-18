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


class StatsLayoutTest(unittest.TestCase):
    """Test findings f-tip and st-bio (17.11.2026): long texts overlapped
    their neighbours in STATISTICS - checked by eye in headless Chrome at
    1600 x 900 in German, held here by the rules that fixed it."""

    WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")

    def _read(self, *parts):
        with open(os.path.join(self.WEB, *parts), encoding="utf-8") as fh:
            return fh.read()

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

    def test_themes_draw_statistics_their_own_way(self):
        """TH1 (user 18.11.2026): each theme its own STATISTICS - console rings and
        pills, industrial segments, station dots and prompt titles without a blinking
        cursor, next flat with a lead figure. The standard theme stays as it was:
        every new rule is bound to a theme other than standard."""
        import re
        css, js = self._read("css", "fis.css"), self._read("js", "views", "statistics.js")
        block = css[css.index("/* 5.0 TH1: each theme's own STATISTICS"):]
        rules = [r for r in re.findall(r"^(:root[^{]*)\{", block, re.M)]
        self.assertTrue(rules)
        for r in rules:
            self.assertRegex(r, r':root\[data-theme="(console|industrial|station|next)"\] (body:not\(\.obs\) )?\.stat-view ')
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
        self.assertEqual(js.count("meter("), 3)
        self.assertIn('rows.length ? "st-row" : "st-row st-lead"', js)

    def test_sub_tabs_hold_every_frame_once(self):
        """Night run 18.11.2026: STATISTICS in sub-tabs of fixed columns -
        every frame in exactly one pane, nothing dropped, labels translated."""
        import re
        js, css, i18n = self._read("js", "views", "statistics.js"), self._read("css", "fis.css"), self._read("js", "i18n.js")
        block = js[js.index("const PANES = ["):js.index("];", js.index("const PANES = ["))]
        keys = re.findall(r'"([A-Za-z]+)"', re.sub(r'N_\("[^"]*"\)', "", block))
        panes = ["overview", "trends", "rates", "learning"]
        frames = list(keys)
        for k in panes:                     # each pane id once; "learning" is a pane and its frame
            frames.remove(k)
        cards = re.findall(r'^  \["([A-Z]+)", N_\(', js, re.M)
        expected = ["ranks", "overTime", "firstFinds", "surfaceMaps", "bioRates", "perSession", "timePerSystem", "learning"] + cards
        self.assertEqual(sorted(frames), sorted(expected))          # each once, none missing
        for k in expected[:8]:
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
