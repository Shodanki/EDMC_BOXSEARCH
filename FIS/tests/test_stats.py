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


if __name__ == "__main__":
    unittest.main()
