# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""5.1.0 STATISTICS: ST7 play patterns, ST10 materials flow, ST11 engineering
history, ST14 the trip report."""

import os
import time
import unittest

from fis import careerstats, craftstats, trip
from fis.live import parse_ts


def ev(stamp, name, **kw):
    return dict({"timestamp": "2026-11-%sZ" % stamp, "event": name}, **kw)


VIEWS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "js", "views")


class PlayPatternsTest(unittest.TestCase):
    def test_minutes_per_weekday_and_hour_and_sessions(self):
        # 23.11.2026 is a Monday: 20:00-20:50 in 10-minute steps, then 2 h quiet, then 23:00-23:20
        evs = [ev("23T20:%02d:00" % m, "Scan") for m in range(0, 60, 10)]
        evs += [ev("23T23:00:00", "FSDJump"), ev("23T23:20:00", "FSDJump")]
        p = careerstats.patterns(evs, local=time.gmtime)
        self.assertEqual(p["grid"][0][20], 50, "Monday 20 h: 50 minutes")
        self.assertEqual(p["grid"][0][23], 20)
        self.assertEqual((p["busy_day"], p["busy_hour"], p["sessions"]), (0, 20, 2))
        self.assertEqual((p["median_s"], p["longest_s"], p["pause_s"]), (35 * 60, 50 * 60, 130 * 60))

    def test_shown_under_history(self):
        with open(os.path.join(VIEWS, "statistics.js"), encoding="utf-8") as fh:
            js = fh.read()
        self.assertIn('["overTime", "playPatterns", "surfaceMaps"]', js)
        self.assertIn('["craft", N_("ENGINEERING"), [[["engineering"], ["materialsFlow"]]]]', js)
        self.assertIn('["trip", N_("TRIP REPORT"), [[["trip"]]]]', js)


class LedgerLayoutTest(unittest.TestCase):
    def test_overview_in_reading_order_and_balanced_columns(self):
        """user 25.11.: LEDGER no longer a full right column beside a half-empty
        grid - the result, the money's ways, the ships, what is open, in
        columns the browser balances: four from 1500 px, then 3, 2, 1."""
        with open(os.path.join(VIEWS, "ledger.js"), encoding="utf-8") as fh:
            js = fh.read()
        self.assertIn('...[head, balance(), weeks(), block("income", t("INCOME")), block("costs", t("RUNNING COSTS")),',
                      js)
        self.assertIn('      block("invest", t("INVESTMENT")), ships(), commander(), losses(), open(), jumps(), carrier()]', js)
        self.assertNotIn("stat-side", js)
        self.assertIn('el("table", { class: "mine-table" }', js[js.index("function ships()"):], "PER SHIP one line a ship")
        with open(os.path.join(os.path.dirname(VIEWS), "..", "css", "fis.css"), encoding="utf-8") as fh:
            css = fh.read()
        self.assertIn(".ledger-cols { column-count: 4;", css)
        self.assertIn("@media (max-width: 1499px) { .ledger-cols { column-count: 3; } }", css)


class CraftTest(unittest.TestCase):
    EVS = [ev("01T10:00:00", "MaterialCollected", Category="Raw", Name="nickel", Count=3),
           ev("01T10:01:00", "LaunchSRV"),
           ev("01T10:02:00", "MaterialCollected", Category="Manufactured", Name="sensorfragment",
              Name_Localised="Sensor Fragment", Count=2),
           ev("01T10:03:00", "DockSRV"),
           ev("01T10:04:00", "SupercruiseExit", Body="X 1 A Ring", BodyType="PlanetaryRing"),
           ev("01T10:05:00", "MaterialCollected", Category="Raw", Name="nickel", Count=4),
           ev("01T10:06:00", "Synthesis", Name="Limpet", Materials=[{"Name": "nickel", "Count": 5}]),
           ev("01T10:07:00", "EngineerCraft", Engineer="Felicity Farseer", BlueprintName="FSD_LongRange", Level=5,
              Ingredients=[{"Name": "nickel", "Count": 1}, {"Name": "sensorfragment", "Count": 1}],
              ApplyExperimentalEffect_Localised="Mass Manager"),
           ev("01T10:08:00", "MaterialTrade", Paid={"Material": "sensorfragment", "Quantity": 1},
              Received={"Material": "iron", "Quantity": 3})]

    def test_engineering(self):
        e = craftstats.engineering(self.EVS)
        self.assertEqual((e["crafts"], e["materials_used"]), (1, 2))
        self.assertEqual(e["engineers"][0]["blueprints"], [{"name": "FSD Long Range", "grade": 5}])
        self.assertEqual(e["last"][0]["effect"], "Mass Manager")

    def test_materials(self):
        m = craftstats.materials(self.EVS, parse_ts("2026-11-01T11:00:00Z"))
        rows = {r["name"]: r for r in m["rows"]}
        self.assertEqual((rows["Nickel"]["got"], rows["Nickel"]["used"]), (7, 6))
        self.assertEqual(rows["Nickel"]["out"], {"synthesis": 5, "engineering": 1})
        self.assertEqual(rows["Nickel"]["from"], "mining", "4 of 7 refined in a ring")
        self.assertEqual((rows["Sensor Fragment"]["from"], rows["Sensor Fragment"]["used"]), ("srv", 2))
        self.assertEqual((m["collected"], m["kinds"], m["recent"]), (9, 2, 9))
        self.assertIsNone(m["per_hour"], "under an hour of play: no pace")
        self.assertEqual(craftstats.blueprint_name("ShieldGenerator_Optimised"), "Shield Generator Optimised")


class TripTest(unittest.TestCase):
    EVS = [ev("01T10:00:00", "FSDJump", StarSystem="Home", SystemAddress=1, StarPos=[0.0, 0.0, 0.0], JumpDist=10.0),
           ev("05T10:00:00", "FSDJump", StarSystem="Home", SystemAddress=1, StarPos=[0.0, 0.0, 0.0], JumpDist=10.0),
           ev("05T10:10:00", "FSDJump", StarSystem="Far", SystemAddress=2, StarPos=[30.0, 0.0, 40.0], JumpDist=50.0),
           ev("05T10:12:00", "Scan", ScanType="Detailed", SystemAddress=2, BodyID=1, BodyName="Far 1",
              WasDiscovered=False, WasMapped=False),
           ev("05T10:20:00", "SAAScanComplete", SystemAddress=2, BodyID=1),
           ev("05T10:25:00", "ScanOrganic", ScanType="Analyse", Species_Localised="Osseus Spiralis"),
           ev("05T10:40:00", "MultiSellExplorationData", TotalEarnings=1_000_000),
           ev("09T10:00:00", "FSDJump", StarSystem="Later", SystemAddress=3, StarPos=[1.0, 0.0, 1.0], JumpDist=5.0)]

    def test_the_span(self):
        r = trip.build(self.EVS, trip.parse_day("2026-11-05"), trip.parse_day("2026-11-06"))
        w, f = r["way"], r["finds"]
        self.assertEqual((w["jumps"], w["ly"], w["systems"], w["new_systems"]), (2, 60, 2, 1), "Home was known before")
        self.assertEqual((w["farthest"], w["longest"]), ({"ly": 50, "system": "Far"}, {"ly": 50.0, "system": "Far"}))
        self.assertEqual(w["route"], [[0.0, 0.0], [30.0, 40.0]])
        self.assertEqual((f["bodies"], f["first_discovered"], f["maps"], f["first_maps"], f["species"]), (1, 1, 1, 1, 1))
        self.assertEqual(r["money"]["income"], 1_000_000)
        self.assertEqual(r["hours"], round(40 / 60.0, 1))

    def test_days_and_regions(self):
        self.assertEqual(trip.parse_day("2026-11-05"), parse_ts("2026-11-05T00:00:00Z"))
        self.assertIsNone(trip.parse_day("05.11.2026"))
        r = trip.build(self.EVS, trip.parse_day("2026-11-05"), trip.parse_day("2026-11-06"),
                       lambda x, y, z: (18, "Inner Orion Spur"))
        self.assertEqual(r["way"]["regions"], ["Inner Orion Spur"])
        self.assertEqual(trip.build([], 0.0, 1.0)["events"], 0)


if __name__ == "__main__":
    unittest.main()
