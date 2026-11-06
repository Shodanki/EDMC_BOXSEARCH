"""Companion API carrier file (written by the plugin): hold per good, tritium in the hold."""

import json
import os
import tempfile
import unittest

from fis import capi, fleet as fl


SAMPLE = {"saved": 1000.0, "source_host": "companion.orerve.net", "data": {
    "name": {"callsign": "V2L-07J", "vanityName": "4541"}, "currentStarSystem": "Synuefe TH-J b42-5",
    "fuel": "889",
    "cargo": [{"commodity": "Tritium", "locName": "Tritium", "qty": 500, "value": 25000000, "stolen": False, "mission": False},
              {"commodity": "Tritium", "locName": "Tritium", "qty": 120, "value": 6000000, "stolen": False, "mission": False},
              {"commodity": "Bromellite", "locName": "Bromellite", "qty": 31, "value": 1500000, "stolen": True, "mission": False},
              {"broken": True}],
}}


class CapiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, capi.FILE)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(SAMPLE, fh)

    def tearDown(self):
        self.tmp.cleanup()

    def test_load(self):
        d = capi.load(self.path, now=1600.0)
        self.assertEqual(d["tritium"], 620)                    # two stacks
        self.assertEqual(d["hold"][0]["key"], "tritium")
        self.assertEqual(d["hold"][1]["stolen"], 31)
        self.assertEqual(d["hold_total"], 651)
        self.assertEqual(d["fuel"], 889.0)
        self.assertEqual(d["age_s"], 600)
        self.assertEqual(d["callsign"], "V2L-07J")

    def test_missing_or_broken(self):
        self.assertIsNone(capi.load(None))
        self.assertIsNone(capi.load(os.path.join(self.tmp.name, "nope.json")))
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        self.assertIsNone(capi.load(self.path))

    def test_hold_extends_range(self):
        load = 8382
        base = fl.carrier_range(889, load)
        more = fl.carrier_range(889 + 620, load - 620)
        self.assertGreater(more["ly"], base["ly"])
        self.assertGreater(more["jumps"], base["jumps"])


if __name__ == "__main__":
    unittest.main()
