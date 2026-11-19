# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""5.0 CT1 CARRIER TRADE: orders with what is still open, market stock, bar,
shipyard and outfitting from the Companion file; the order history from the
journal; nothing without the file but the history."""

import json
import os
import tempfile
import unittest

from fis import capi, carriertrade

OWN = 3700000001
DATA = {"saved": 1000.0, "data": {
    "name": {"callsign": "XXX-000"},
    "capacity": {"shipPacks": 1, "modulePacks": 4, "cargoForSale": 120, "cargoNotForSale": 900,
                 "microresourceCapacityTotal": 1000, "microresourceCapacityUsed": 30},
    "marketFinances": {"cargoTotalValue": 5000000, "allTimeProfit": 585390, "numCommodsForSale": 1,
                       "numCommodsPurchaseOrders": 2, "balanceAllocForPurchaseOrders": 21000000},
    "blackmarketFinances": {"allTimeProfit": 0},
    "finance": {"bartender": {"microresourcesTotalValue": 90000, "allTimeProfit": 12000, "microresourcesForSale": 1,
                              "microresourcesPurchaseOrders": 1, "profitHistory": [0, 5000, 7000]}},
    "orders": {"commodities": {
        "sales": {"128": {"name": "Bromellite", "stock": 120, "price": 50000, "blackmarket": False}},
        "purchases": [{"name": "tritium", "total": 2000, "outstanding": 1500, "price": 10000, "blackmarket": False},
                      {"name": "gold", "total": 10, "outstanding": 0, "price": 9000, "blackmarket": False}]},
        "onfootmicroresources": {
            "sales": [{"name": "graphene", "locName": "Graphene", "stock": 30, "price": 3000}],
            "purchases": [{"name": "suitschematic", "locName": "Suit Schematic", "total": 5, "outstanding": 5,
                           "price": 2000}]}},
    "commodities": {"commodities": [
        {"name": "Tritium", "locName": "Tritium", "categoryname": "Chemicals", "stock": 0, "demand": 1500,
         "buyPrice": 0, "sellPrice": 10000},
        {"name": "Drones", "locName": "Limpet", "categoryname": "NonMarketable", "stock": 999999, "demand": 9999999}]},
    "ships": {"shipyard_list": {"Adder": {"name": "Adder", "basevalue": 87808, "stock": 2}}, "discount_list": []},
    "modules": {"1": {"name": "Hpt_MiningLaser_Fixed_Medium", "category": "utility", "cost": 22576, "stock": 20},
                "2": {"name": "Int_FighterBay", "category": "module", "cost": 0, "stock": -1, "bundle": True}},
    "market": {"services": {"commodities": "ok", "bartender": "unmanned", "shipyard": "ok", "outfitting": "ok"}},
}}
EVENTS = [
    {"timestamp": "2026-05-17T08:43:40Z", "event": "CarrierTradeOrder", "CarrierID": OWN, "Commodity": "tritium",
     "PurchaseOrder": 2000, "Price": 56926},
    {"timestamp": "2026-05-22T15:58:12Z", "event": "CarrierTradeOrder", "CarrierID": OWN, "Commodity": "tritium",
     "CancelTrade": True},
    {"timestamp": "2026-05-23T10:00:00Z", "event": "CarrierTradeOrder", "CarrierID": OWN, "Commodity": "gold",
     "Commodity_Localised": "Gold", "SaleOrder": 10, "Price": 9000},
    {"timestamp": "2026-05-24T10:00:00Z", "event": "CarrierTradeOrder", "CarrierID": 99, "Commodity": "silver",
     "SaleOrder": 1, "Price": 1},
]


class CarrierTradeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, capi.FILE)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(DATA, fh)

    def tearDown(self):
        self.tmp.cleanup()

    def test_market_orders_and_demand(self):
        out = carriertrade.build_trade(self.path, EVENTS, OWN, now=1600.0)
        m = out["capi"]["market"]
        self.assertEqual(out["capi"]["age_s"], 600)
        self.assertEqual(m["sales"], [{"name": "Bromellite", "stock": 120, "price": 50000, "value": 6000000,
                                       "black": False}])
        tri = m["purchases"][0]
        self.assertEqual((tri["name"], tri["delivered"], tri["open_cr"]), ("Tritium", 500, 15000000))
        self.assertEqual(m["finances"]["profit"], 585390)
        self.assertEqual([r["name"] for r in m["stock"]], ["Tritium"])        # no limpets as goods
        # what is still wanted: market and bar, the filled order left out
        self.assertEqual(out["demand"]["units"], 1505)
        self.assertEqual(out["demand"]["cr"], 15000000 + 10000)
        self.assertEqual([r["where"] for r in out["demand"]["rows"]], ["market", "bar"])

    def test_bar_shipyard_outfitting(self):
        c = carriertrade.build_trade(self.path, [], OWN, now=1600.0)["capi"]
        self.assertEqual(c["bar"]["status"], "unmanned")
        self.assertEqual(c["bar"]["sales"][0]["value"], 90000)
        self.assertEqual(c["bar"]["finances"]["profit"], 12000)
        self.assertEqual(c["bar"]["profit_history"], [0, 5000, 7000])
        self.assertEqual(c["shipyard"]["ships"], [{"name": "Adder", "stock": 2, "price": 87808}])
        o = c["outfitting"]
        self.assertEqual((o["kinds"], o["units"], o["bundled"], o["value"]), (2, 20, 1, 20 * 22576))
        self.assertEqual(o["modules"][0]["name"], "Mining Laser (F) M")

    def test_history_own_carrier_only(self):
        h = carriertrade.history(EVENTS, OWN)
        self.assertEqual([x["kind"] for x in h], ["sell", "cancel", "buy"])     # newest first
        self.assertEqual(h[0]["name"], "Gold")
        self.assertEqual(h[2]["name"], "Tritium")
        self.assertEqual((h[2]["qty"], h[2]["price"]), (2000, 56926))

    def test_without_companion_file(self):
        out = carriertrade.build_trade(os.path.join(self.tmp.name, "none.json"), EVENTS, OWN)
        self.assertIsNone(out["capi"])
        self.assertEqual(len(out["history"]), 3)
        self.assertNotIn("demand", out)

    def test_file_is_only_read(self):
        before = os.stat(self.path).st_mtime_ns
        carriertrade.build_trade(self.path, EVENTS, OWN)
        self.assertEqual(os.stat(self.path).st_mtime_ns, before)


if __name__ == "__main__":
    unittest.main()
