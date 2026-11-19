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

    def test_mean_kept_after_a_carrier(self):
        # h-tab (17.11.): the last market was a fleet carrier without
        # MeanPrice and the column was empty - the means stay now
        path = os.path.join(self.jd, "market_means.json")
        out = trade.build_trade(_Archive(self.evs), {"status": {"flags": 0}}, self.jd, path)
        tri = out["rows"][1]
        self.assertEqual((tri["mean"], tri["mean_from"]["station"], tri["vs_mean"]), (50000, "Test Port", -5))
        self.assertEqual((out["means"], out["sales"], out["earned"]), (2, 3, 100 * 40000 + 300 * 50000 + 90000))
        with open(os.path.join(self.jd, "Market.json"), "w", encoding="utf-8") as fh:
            json.dump({"timestamp": "2026-11-17T12:00:00Z", "MarketID": 99, "StationName": "K7Q-1XZ",
                       "StationType": "FleetCarrier", "Items": [
                           {"Name": "$tritium_name;", "Name_Localised": "Tritium", "SellPrice": 30000}]}, fh)
        out = trade.build_trade(_Archive(self.evs), {"status": {"flags": 0}}, self.jd, path)
        self.assertEqual((out["rows"][1]["mean"], out["rows"][0]["mean"]), (50000, 40000))
        # a newer market with a mean replaces it; an older one does not
        newer = {"timestamp": "2026-11-18T09:00:00Z", "StationName": "New Port",
                 "Items": [{"Name": "$tritium_name;", "MeanPrice": 51000}]}
        older = {"timestamp": "2026-11-01T09:00:00Z", "StationName": "Old Port",
                 "Items": [{"Name": "$tritium_name;", "MeanPrice": 10}]}
        self.assertEqual(trade.remember_means(path, newer)["tritium"]["mean"], 51000)
        self.assertEqual(trade.remember_means(path, older)["tritium"]["station"], "New Port")

    def test_means_from_the_edd_archive(self):
        """h-tab (user 19.11.): only carrier markets lately - no mean; the
        station markets EDDiscovery kept fill the column, a kept newer mean
        from an own station market still wins."""
        import sqlite3
        db = os.path.join(self.jd, "EDDUser.sqlite")
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE JournalEntries (Id INTEGER PRIMARY KEY AUTOINCREMENT, CommanderId INTEGER, "
                    "EventType TEXT, EventData TEXT)")
        may = [{"Name": "$Gold_Name;", "MeanPrice": 9500}, {"Name": "$tritium_name;", "MeanPrice": 9},
               {"Name": "$bromellite_name;", "MeanPrice": 0}]
        for ts, st, items in (("2026-05-01T10:00:00Z", "Old Hub", [{"Name": "$gold_name;", "MeanPrice": 9000}]),
                              ("2026-05-21T20:29:27Z", "May Hub", may)):
            con.execute("INSERT INTO JournalEntries (CommanderId, EventType, EventData) VALUES (1, 'Market', ?)",
                        (json.dumps({"timestamp": ts, "event": "Market", "StationName": st, "Items": items}),))
        con.execute("INSERT INTO JournalEntries (CommanderId, EventType, EventData) VALUES (1, 'Docked', '{}')")
        con.commit()
        con.close()
        trade._EDD_MEANS.update(path=None, t=0.0, means={})
        path = os.path.join(self.jd, "market_means.json")
        out = trade.build_trade(_Archive(self.evs), {"status": {"flags": 0}}, self.jd, path, edd_path=db)
        rows = {r["key"]: r for r in out["rows"]}
        g = rows["gold"]
        self.assertEqual((g["mean"], g["mean_from"]["station"], g["mean_from"]["edd"], g["vs_mean"]),
                         (9500, "May Hub", True, -5))
        # the station market of November (Market.json) is newer than EDD's May
        self.assertEqual((rows["tritium"]["mean"], rows["tritium"]["mean_from"]["edd"]), (50000, False))
        self.assertEqual(rows["bromellite"]["mean"], 40000)
        self.assertEqual(trade.edd_means(None), {})
        trade._EDD_MEANS.update(path=None, t=0.0, means={})

    def test_key(self):
        self.assertEqual(trade.key_of("$lowtemperaturediamond_name;"), "lowtemperaturediamond")
        self.assertEqual(trade.key_of("Tritium"), "tritium")


if __name__ == "__main__":
    unittest.main()
