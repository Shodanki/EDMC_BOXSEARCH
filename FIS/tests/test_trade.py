# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""TRADE (HD1): own sale prices per commodity, the galactic mean, and the
market's offer only while docked at it."""

import json
import os
import tempfile
import unittest

from fis import trade


class _Archive:
    def __init__(self, evs):
        self.evs = evs

    def events(self):
        return self.evs


def _sell(ts, typ, n, price, paid=0):
    return {"timestamp": ts, "event": "MarketSell", "Type": "$%s_name;" % typ.lower(), "Type_Localised": typ,
            "Count": n, "SellPrice": price, "TotalSale": n * price, "AvgPricePaid": paid}


class TradeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.jd = self.tmp.name
        with open(os.path.join(self.jd, "Cargo.json"), "w", encoding="utf-8") as fh:
            json.dump({"Vessel": "Ship", "Inventory": [{"Name": "bromellite", "Name_Localised": "Bromellite", "Count": 12},
                                                       {"Name": "drones", "Count": 40}]}, fh)
        with open(os.path.join(self.jd, "Market.json"), "w", encoding="utf-8") as fh:
            json.dump({"timestamp": "2026-11-17T10:05:00Z", "MarketID": 77, "StationName": "Test Port",
                       "StationType": "Coriolis", "Items": [
                           {"Name": "$tritium_name;", "Name_Localised": "Tritium", "SellPrice": 52000,
                            "MeanPrice": 50000, "Demand": 300},
                           {"Name": "$bromellite_name;", "Name_Localised": "Bromellite", "SellPrice": 0,
                            "MeanPrice": 40000, "Demand": 0}]}, fh)
        self.evs = [_sell("2026-11-01T10:00:00Z", "Tritium", 100, 40000),
                    _sell("2026-11-02T10:00:00Z", "Tritium", 300, 50000),
                    _sell("2026-11-03T10:00:00Z", "Gold", 10, 9000, paid=8000),
                    {"timestamp": "2026-11-04T10:00:00Z", "event": "MiningRefined", "Type": "$tritium_name;",
                     "Type_Localised": "Tritium"},
                    {"timestamp": "2026-11-17T10:00:00Z", "event": "Docked", "MarketID": 77}]

    def tearDown(self):
        self.tmp.cleanup()

    def test_rows_and_order(self):
        out = trade.build_trade(_Archive(self.evs), {"status": {"flags": 0}}, self.jd)
        self.assertEqual([r["key"] for r in out["rows"]], ["bromellite", "tritium", "gold"])   # hold, mined, sold
        tri = out["rows"][1]["sold"]
        self.assertEqual((tri["t"], tri["avg"], tri["lo"], tri["hi"], tri["sales"], tri["own"]),
                         (400, 47500, 40000, 50000, 2, True))
        self.assertFalse(out["rows"][2]["sold"]["own"])                    # bought, then sold
        self.assertEqual((out["rows"][0]["hold"], out["rows"][0]["mean"]), (12, 40000))
        self.assertFalse(out["docked_here"])
        self.assertIsNone(out["rows"][1]["here"])                          # not docked: no offer

    def test_offer_only_while_docked_at_that_market(self):
        out = trade.build_trade(_Archive(self.evs), {"status": {"flags": 1}}, self.jd)
        self.assertTrue(out["docked_here"])
        self.assertEqual(out["rows"][1]["here"], {"price": 52000, "demand": 300})
        moved = self.evs[:-1] + [{"timestamp": "2026-11-17T11:00:00Z", "event": "Docked", "MarketID": 88}]
        self.assertFalse(trade.build_trade(_Archive(moved), {"status": {"flags": 1}}, self.jd)["docked_here"])

    def test_key(self):
        self.assertEqual(trade.key_of("$lowtemperaturediamond_name;"), "lowtemperaturediamond")
        self.assertEqual(trade.key_of("Tritium"), "tritium")


if __name__ == "__main__":
    unittest.main()
