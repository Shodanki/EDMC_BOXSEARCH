# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""5.0 CT2: the carrier's money - Frontier's figures (upkeep, crew, market
and bar profit) and the journal's (transfers, jumps, services, the upkeep
estimate over the period)."""

import json
import os
import tempfile
import unittest

from fis import capi, carriermoney

OWN = 3700000001
DAY = 86400.0
DATA = {"saved": 1000.0, "data": {
    "finance": {"bankBalance": 7000000000, "bankReservedBalance": 2700000000, "taxation": 0,
                "service_taxation": {"rearm": 5, "refuel": 5}, "maintenance": 27383111, "maintenanceToDate": 22509553,
                "coreCost": 5000000, "servicesCost": 22383111, "servicesCostToDate": 17509553, "jumpsCost": 0,
                "numJumps": 0, "debtThreshold": -300000000,
                "bartender": {"allTimeProfit": 12000, "profitHistory": [0, 5000, 7000],
                              "balanceAllocForPurchaseOrders": 10000}},
    "marketFinances": {"allTimeProfit": 585390, "cargoTotalValue": 335567017, "balanceAllocForPurchaseOrders": 20668000},
    "blackmarketFinances": {"allTimeProfit": 0},
    "servicesCrew": {
        "shipyard": {"crewMember": {"enabled": "YES", "salary": 6500000, "hiringPrice": 250000000},
                     "invoicesWeekToDate": [{"wages": 5069580, "type": "current"},
                                            {"wages": 6480633, "type": "expected"}]},
        "bartender": {"crewMember": {"enabled": "NO", "salary": 1250000, "hiringPrice": 200000000}}},
}}
CARRIER = {"stats": {"CarrierID": OWN},
           "balances": [(0.0, 1000000000), (5 * DAY, 980000000), (10 * DAY, 1060000000)],
           "transfers": [{"ts": 7 * DAY, "deposit": 100000000, "withdraw": 0}]}
EVENTS = [
    {"timestamp": "1970-01-02T00:00:00Z", "event": "CarrierJumpRequest", "CarrierID": OWN},
    {"timestamp": "1970-01-03T00:00:00Z", "event": "CarrierJumpCancelled", "CarrierID": OWN},
    {"timestamp": "1970-01-04T00:00:00Z", "event": "CarrierJumpRequest", "CarrierID": OWN},
    {"timestamp": "1970-01-04T00:00:00Z", "event": "CarrierJumpRequest", "CarrierID": 99},
    {"timestamp": "1970-01-06T00:00:00Z", "event": "CarrierCrewServices", "CarrierID": OWN, "CrewRole": "Bartender",
     "Operation": "Pause"},
]


class CarrierMoneyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, capi.FILE)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(DATA, fh)

    def tearDown(self):
        self.tmp.cleanup()

    def test_frontier_figures(self):
        F = carriermoney.build(self.path, CARRIER, EVENTS, now=1600.0)["frontier"]
        self.assertEqual(F["age_s"], 600)
        self.assertEqual(F["per_week"], F["core"] + F["services"])
        self.assertEqual((F["week_to_date"], F["market_profit"], F["bar_profit"]), (22509553, 585390, 12000))
        self.assertEqual(F["orders_reserved"], 20678000)
        self.assertEqual([c["role"] for c in F["crew"]], ["shipyard", "bartender"])      # by salary
        self.assertEqual((F["crew"][0]["current"], F["crew"][0]["expected"]), (5069580, 6480633))
        self.assertFalse(F["crew"][1]["enabled"])

    def test_journal_period(self):
        J = carriermoney.build(None, CARRIER, EVENTS)["journal"]
        self.assertEqual((J["deposit"], J["withdraw"], J["transfers"], J["readings"]), (100000000, 0, 1, 3))
        self.assertEqual(J["jumps"], 1)                       # two ordered, one cancelled; the stranger's not
        self.assertEqual(J["services"][0]["op"], "Pause")
        # 1000 -> 1060 M with 100 M paid in: 40 M upkeep over 10 days, an estimate
        self.assertEqual(J["upkeep"]["cost"], 40000000)
        # from day 4 on: one reading before the deposit, one after -> 5 days, 1060-980-100 = -20 M
        J4 = carriermoney.build(None, CARRIER, EVENTS, since=4 * DAY)["journal"]
        self.assertEqual((J4["readings"], J4["upkeep"]["cost"], J4["jumps"]), (2, 20000000, 0))

    def test_without_file_or_carrier(self):
        self.assertIsNone(carriermoney.build(self.path, None, EVENTS))
        self.assertIsNone(carriermoney.build(os.path.join(self.tmp.name, "x.json"), CARRIER, [])["frontier"])


if __name__ == "__main__":
    unittest.main()
